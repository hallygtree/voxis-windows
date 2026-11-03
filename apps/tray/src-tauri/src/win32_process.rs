//! Windows process inspection for the recorder identity check in miris.rs:
//! there is no `ps`, so the command line is read from the process itself.
//! Raw ntdll/kernel32 bindings rather than a crate: four calls with a fixed
//! C ABI, against windows-sys feature names that move between releases.

use std::ffi::c_void;

const PROCESS_QUERY_LIMITED_INFORMATION: u32 = 0x1000;
/// PROCESSINFOCLASS::ProcessCommandLineInformation (Windows 8.1+).
const PROCESS_COMMAND_LINE_INFORMATION: u32 = 60;

#[repr(C)]
struct UnicodeString {
    length: u16, // bytes, not characters
    maximum_length: u16,
    buffer: *const u16,
}

#[link(name = "kernel32")]
extern "system" {
    fn OpenProcess(access: u32, inherit_handle: i32, pid: u32) -> *mut c_void;
    fn CloseHandle(handle: *mut c_void) -> i32;
}
#[link(name = "ntdll")]
extern "system" {
    fn NtQueryInformationProcess(
        handle: *mut c_void, class: u32, info: *mut c_void, len: u32, ret_len: *mut u32,
    ) -> i32;
}

/// The process's command line, or "" when it is gone or not ours to read
/// - both of which the caller must read as "not the recorder".
pub fn command_line(pid: i32) -> String {
    if pid <= 0 {
        return String::new();
    }
    unsafe {
        let handle = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, 0, pid as u32);
        if handle.is_null() {
            return String::new();
        }
        // the first call sizes the buffer; u64 storage keeps it aligned
        // for the UNICODE_STRING header the kernel writes at its start
        let mut needed = 0u32;
        NtQueryInformationProcess(
            handle, PROCESS_COMMAND_LINE_INFORMATION, std::ptr::null_mut(), 0, &mut needed,
        );
        let mut buf = vec![0u64; (needed as usize).div_ceil(8).max(2)];
        let status = NtQueryInformationProcess(
            handle,
            PROCESS_COMMAND_LINE_INFORMATION,
            buf.as_mut_ptr().cast(),
            (buf.len() * 8) as u32,
            &mut needed,
        );
        CloseHandle(handle);
        if status < 0 {
            return String::new();
        }
        let header = &*(buf.as_ptr() as *const UnicodeString);
        if header.buffer.is_null() {
            return String::new();
        }
        let chars = std::slice::from_raw_parts(header.buffer, header.length as usize / 2);
        String::from_utf16_lossy(chars)
    }
}

/// Splits a command line the way Python's list2cmdline built it: spaces
/// separate arguments unless inside double quotes, which are dropped.
/// Backslash escapes before a quote are not handled - nothing here passes
/// an argument that ends in a backslash or contains a quote.
pub fn split_command_line(command: &str) -> Vec<String> {
    let mut args = Vec::new();
    let mut current = String::new();
    let mut quoted = false;
    let mut started = false;
    for c in command.chars() {
        match c {
            '"' => {
                quoted = !quoted;
                started = true;
            }
            c if c.is_whitespace() && !quoted => {
                if started {
                    args.push(std::mem::take(&mut current));
                    started = false;
                }
            }
            c => {
                current.push(c);
                started = true;
            }
        }
    }
    if started {
        args.push(current);
    }
    args
}
