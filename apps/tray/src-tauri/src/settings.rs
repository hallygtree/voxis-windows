//! Config files the tray owns or edits: tray.json + laris-settings.json
//! (owned, JSON, atomic writes) and miris config.toml (edited via toml_edit
//! so hand-written comments survive).

use std::path::{Path, PathBuf};

fn home() -> PathBuf {
    dirs::home_dir().expect("no home dir")
}

pub fn config_dir() -> PathBuf {
    home().join(".config/voice-at")
}

pub fn laris_settings_path() -> PathBuf {
    config_dir().join("laris-settings.json")
}

pub fn read_json_map(path: &Path) -> serde_json::Map<String, serde_json::Value> {
    std::fs::read_to_string(path)
        .ok()
        .and_then(|raw| serde_json::from_str::<serde_json::Value>(&raw).ok())
        .and_then(|v| v.as_object().cloned())
        .unwrap_or_default()
}

/// tmp + rename in the same dir: other processes read these files.
fn write_atomic(path: &Path, body: &str) -> Result<(), String> {
    let parent = path.parent().ok_or("path has no parent")?;
    std::fs::create_dir_all(parent).map_err(|e| e.to_string())?;
    let name = path.file_name().unwrap_or_default().to_string_lossy();
    let tmp = parent.join(format!(".{name}.tmp"));
    std::fs::write(&tmp, body).map_err(|e| e.to_string())?;
    std::fs::rename(&tmp, path).map_err(|e| {
        let _ = std::fs::remove_file(&tmp); // don't litter the config dir
        e.to_string()
    })
}

pub fn write_json_atomic(path: &Path, value: &serde_json::Value) -> Result<(), String> {
    let body = serde_json::to_string_pretty(value).map_err(|e| e.to_string())?;
    write_atomic(path, &body)
}

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
#[serde(default)] // partial tray.json keeps the user's set fields, defaults the rest
pub struct TrayConfig {
    pub miris_bin: String,
    pub laris_dir: String,
    pub miris_home: String,
}

impl Default for TrayConfig {
    fn default() -> Self {
        // GUI apps don't inherit shell PATH - absolute paths only
        let h = home().to_string_lossy().into_owned();
        Self {
            miris_bin: format!("{h}/.local/bin/miris"),
            laris_dir: format!("{h}/code/voxis/packages/laris"),
            miris_home: format!("{h}/.miris"),
        }
    }
}

pub fn load_tray_config() -> TrayConfig {
    let path = config_dir().join("tray.json");
    std::fs::read_to_string(&path)
        .ok()
        .and_then(|raw| serde_json::from_str(&raw).ok())
        .unwrap_or_default()
}

pub fn read_miris_config(path: &Path) -> Result<serde_json::Value, String> {
    let raw = std::fs::read_to_string(path).map_err(|e| e.to_string())?;
    let doc: toml_edit::DocumentMut = raw
        .parse()
        .map_err(|e: toml_edit::TomlError| e.to_string())?;
    let vault_root = doc
        .get("vault_root")
        .and_then(|v| v.as_str())
        .unwrap_or("~/vault")
        .to_owned();
    let llm_command: Vec<String> = doc
        .get("llm_command")
        .and_then(|v| v.as_array())
        .map(|a| {
            a.iter()
                .filter_map(|x| x.as_str().map(String::from))
                .collect()
        })
        .unwrap_or_default();
    let categories: serde_json::Map<String, serde_json::Value> = doc
        .get("categories")
        // as_table_like also accepts inline-table syntax - a silent None here
        // would show empty categories and wipe them on the next save
        .and_then(|v| v.as_table_like())
        .map(|t| {
            t.iter()
                .filter_map(|(k, v)| {
                    v.as_str()
                        .map(|s| (k.to_owned(), serde_json::Value::String(s.to_owned())))
                })
                .collect()
        })
        .unwrap_or_default();
    Ok(serde_json::json!({
        "vault_root": vault_root,
        "llm_command": llm_command,
        "categories": categories,
    }))
}

pub fn update_miris_config(
    path: &Path,
    vault_root: &str,
    llm_command: &[String],
    categories: &[(String, String)],
) -> Result<(), String> {
    let raw = std::fs::read_to_string(path).map_err(|e| e.to_string())?;
    let mut doc: toml_edit::DocumentMut = raw
        .parse()
        .map_err(|e: toml_edit::TomlError| e.to_string())?;
    doc["vault_root"] = toml_edit::value(vault_root);
    let mut arr = toml_edit::Array::new();
    for part in llm_command {
        arr.push(part.as_str());
    }
    doc["llm_command"] = toml_edit::value(arr);
    let mut table = toml_edit::Table::new();
    for (key, folder) in categories {
        table[key.as_str()] = toml_edit::value(folder.as_str());
    }
    doc["categories"] = toml_edit::Item::Table(table);
    // same tmp+rename discipline as the JSON files: config.toml is the user's
    // hand-written file and a miris run may read it concurrently
    write_atomic(path, &doc.to_string())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;

    #[test]
    fn read_json_map_missing_corrupt_or_non_object_is_empty() {
        let tmp = tempfile::tempdir().unwrap();
        assert!(read_json_map(&tmp.path().join("nope.json")).is_empty());
        let p = tmp.path().join("bad.json");
        fs::write(&p, "[1,2]").unwrap();
        assert!(read_json_map(&p).is_empty());
    }

    #[test]
    fn write_json_atomic_roundtrip_no_tmp_leftover() {
        let tmp = tempfile::tempdir().unwrap();
        let p = tmp.path().join("deep/dir/s.json");
        let value = serde_json::json!({"DICTATE_KEY": "f13"});
        write_json_atomic(&p, &value).unwrap();
        assert_eq!(read_json_map(&p).get("DICTATE_KEY").unwrap(), "f13");
        let leftovers: Vec<_> = fs::read_dir(p.parent().unwrap())
            .unwrap()
            .filter_map(|e| e.ok())
            .filter(|e| e.file_name().to_string_lossy().ends_with(".tmp"))
            .collect();
        assert!(leftovers.is_empty());
    }

    #[test]
    fn tray_config_defaults() {
        let cfg = TrayConfig::default();
        assert!(cfg.miris_bin.ends_with("/.local/bin/miris"));
        assert!(cfg.laris_dir.ends_with("/code/voxis/packages/laris"));
        assert!(cfg.miris_home.ends_with("/.miris"));
    }

    const SAMPLE_TOML: &str = "\
vault_root = \"~/vault\"
inbox = \"inbox\"
# swapping provider = edit this line, never code
llm_command = [\"agy\", \"--model\", \"Gemini 3.5 Flash (Medium)\", \"-p\"]

[categories]
trabalho = \"work-notes\"
";

    #[test]
    fn miris_config_read() {
        let tmp = tempfile::tempdir().unwrap();
        let p = tmp.path().join("config.toml");
        fs::write(&p, SAMPLE_TOML).unwrap();
        let cfg = read_miris_config(&p).unwrap();
        assert_eq!(cfg["vault_root"], "~/vault");
        assert_eq!(cfg["llm_command"][3], "-p");
        assert_eq!(cfg["categories"]["trabalho"], "work-notes");
    }

    #[test]
    fn miris_config_read_inline_categories_table() {
        let tmp = tempfile::tempdir().unwrap();
        let p = tmp.path().join("config.toml");
        fs::write(
            &p,
            "vault_root = \"~/vault\"\nllm_command = [\"agy\"]\ncategories = { trabalho = \"work-notes\" }\n",
        )
        .unwrap();
        let cfg = read_miris_config(&p).unwrap();
        assert_eq!(cfg["categories"]["trabalho"], "work-notes");
    }

    #[test]
    fn miris_config_update_preserves_comments() {
        let tmp = tempfile::tempdir().unwrap();
        let p = tmp.path().join("config.toml");
        fs::write(&p, SAMPLE_TOML).unwrap();
        update_miris_config(
            &p,
            "~/vault2",
            &["agy".into(), "-p".into()],
            &[("entrevistas".into(), "work-notes/interviews".into())],
        )
        .unwrap();
        let raw = fs::read_to_string(&p).unwrap();
        assert!(raw.contains("# swapping provider"));
        assert!(raw.contains("vault_root = \"~/vault2\""));
        assert!(raw.contains("entrevistas"));
        assert!(!raw.contains("trabalho")); // categories table fully replaced
    }
}
