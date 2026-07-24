import { invoke } from "@tauri-apps/api/core";

type Settings = {
  laris: Record<string, string>;
  miris: {
    vault_root?: string;
    llm_command?: string[];
    categories?: Record<string, string>;
  };
  theme: {
    archetype: string;
    palette: string;
    position: string;
    size: number;
  } | null;
  laris_alive: boolean;
  version: string;
  platform: string; // std::env::consts::OS: "windows" | "macos" | "linux"
};

// mirrors laris/hotkey.py _ALLOWED (ctrl/alt are broken as global hotkeys on macOS)
const DICTATE_KEYS = [
  "cmd_r", "cmd_l", "shift_r", "shift_l",
  "f5", "f6", "f7", "f8", "f9", "f10", "f11", "f12", "f13", "f14", "f15",
];

const $ = <T extends HTMLElement>(sel: string) =>
  document.querySelector(sel) as T;

// Set from the backend's std::env::consts::OS on load(). Not sniffed from
// navigator.userAgent: a wrong answer here is silent (the user saves a
// DICTATE_KEY that never fires, or an STT key the engine never reads), so it
// comes from the process that actually spawns the engine. bind()'s handlers
// only run after load() resolved.
let isWindows = false;

function feedback(msg: string, isError = false) {
  const el = $<HTMLParagraphElement>("#feedback");
  el.textContent = msg;
  el.classList.toggle("error", isError);
  setTimeout(() => { el.textContent = ""; }, 4000);
}

function categoryRow(name = "", folder = ""): HTMLTableRowElement {
  const tr = document.createElement("tr");
  tr.innerHTML = `
    <td><input type="text" class="cat-name" value=""></td>
    <td><input type="text" class="cat-folder" value=""></td>
    <td><button type="button" class="remove" aria-label="Remover categoria">x</button></td>`;
  (tr.querySelector(".cat-name") as HTMLInputElement).value = name;
  (tr.querySelector(".cat-folder") as HTMLInputElement).value = folder;
  (tr.querySelector(".remove") as HTMLButtonElement).onclick = () => tr.remove();
  return tr;
}

async function load() {
  const s = await invoke<Settings>("get_settings");
  isWindows = s.platform === "windows";

  const keySelect = $<HTMLSelectElement>("#dictate-key");
  keySelect.innerHTML = DICTATE_KEYS
    .map((k) => `<option value="${k}">${k}</option>`)
    .join("");
  // an unknown stored value would leave the select unselected and submit ""
  // must match laris/config.py::_DEFAULT_DICTATE_KEY - cmd_r does not exist
  // on Windows, so a cmd_r default there is a hotkey that never fires
  const defaultKey = isWindows ? "shift_r" : "cmd_r";
  keySelect.value = DICTATE_KEYS.includes(s.laris.DICTATE_KEY ?? "")
    ? s.laris.DICTATE_KEY
    : defaultKey;
  $<HTMLInputElement>("#hands-free").checked =
    s.laris.ASSISTANT_MODE === "always_on";
  // Windows runs faster-whisper (plain size names, STT_MODEL_FASTER); macOS
  // runs mlx (repo ids, STT_MODEL). The field is free text on purpose - a
  // local model dir is valid too - so the placeholder is the only hint the
  // user gets that the two are not interchangeable.
  const model = $<HTMLInputElement>("#stt-model");
  if (isWindows) {
    model.value = s.laris.STT_MODEL_FASTER ?? "large-v3-turbo";
    model.placeholder = "large-v3-turbo";
    model.title =
      "faster-whisper: tiny | base | small | medium | large-v3 | large-v3-turbo";
  } else {
    model.value = s.laris.STT_MODEL ?? "mlx-community/whisper-large-v3-turbo-q4";
    model.placeholder = "mlx-community/whisper-large-v3-turbo-q4";
    model.title = "mlx-whisper model id";
  }
  $<HTMLSelectElement>("#noise").value = s.laris.NOISE_REDUCTION ?? "on";

  $<HTMLInputElement>("#vault-root").value = s.miris.vault_root ?? "~/vault";
  $<HTMLTextAreaElement>("#llm-command").value =
    (s.miris.llm_command ?? []).join("\n");
  const tbody = $<HTMLTableSectionElement>("#categories tbody");
  tbody.innerHTML = "";
  for (const [name, folder] of Object.entries(s.miris.categories ?? {})) {
    tbody.appendChild(categoryRow(name, folder));
  }

  const orbOffline = !s.laris_alive || s.theme === null;
  $<HTMLParagraphElement>("#orb-offline").hidden = !orbOffline;
  for (const id of ["#orb-archetype", "#orb-palette", "#orb-position", "#orb-size", "#save-orb"]) {
    ($(id) as HTMLInputElement | HTMLSelectElement | HTMLButtonElement).disabled = orbOffline;
  }
  if (s.theme) {
    $<HTMLSelectElement>("#orb-archetype").value = s.theme.archetype;
    $<HTMLSelectElement>("#orb-palette").value = s.theme.palette;
    $<HTMLSelectElement>("#orb-position").value = s.theme.position;
    $<HTMLInputElement>("#orb-size").value = String(s.theme.size);
  }

  $<HTMLSpanElement>("#version").textContent = s.version;
}

function bind() {
  $<HTMLButtonElement>("#add-category").onclick = () =>
    $<HTMLTableSectionElement>("#categories tbody").appendChild(categoryRow());

  $<HTMLButtonElement>("#save-laris").onclick = async () => {
    try {
      const updates: Record<string, string> = {
        DICTATE_KEY: $<HTMLSelectElement>("#dictate-key").value,
        ASSISTANT_MODE: $<HTMLInputElement>("#hands-free").checked
          ? "always_on"
          : "ptt",
        NOISE_REDUCTION: $<HTMLSelectElement>("#noise").value,
      };
      // On Windows, persist STT_MODEL_FASTER; on macOS, persist STT_MODEL
      const modelValue = $<HTMLInputElement>("#stt-model").value.trim();
      if (isWindows) {
        updates.STT_MODEL_FASTER = modelValue;
      } else {
        updates.STT_MODEL = modelValue;
      }
      await invoke("save_laris_settings", {
        updates,
      });
      feedback("Ditado salvo.");
    } catch (e) {
      feedback(String(e), true);
    }
  };

  $<HTMLButtonElement>("#save-miris").onclick = async () => {
    const categories: [string, string][] = [];
    let incomplete = 0;
    for (const tr of $<HTMLTableSectionElement>("#categories tbody").rows) {
      const name = (tr.querySelector(".cat-name") as HTMLInputElement).value.trim();
      const folder = (tr.querySelector(".cat-folder") as HTMLInputElement).value.trim();
      if (name && folder) categories.push([name, folder]);
      else if (name || folder) incomplete += 1;
    }
    if (incomplete > 0) {
      feedback(`${incomplete} categoria(s) incompleta(s) - preencha nome e pasta.`, true);
      return;
    }
    try {
      await invoke("save_miris_config", {
        vaultRoot: $<HTMLInputElement>("#vault-root").value.trim(),
        llmCommand: $<HTMLTextAreaElement>("#llm-command").value
          .split("\n").map((l) => l.trim()).filter(Boolean),
        categories,
      });
      feedback("Reuniões salvas.");
    } catch (e) {
      feedback(String(e), true);
    }
  };

  $<HTMLButtonElement>("#save-orb").onclick = async () => {
    try {
      await invoke("save_theme", {
        updates: {
          archetype: $<HTMLSelectElement>("#orb-archetype").value,
          palette: $<HTMLSelectElement>("#orb-palette").value,
          position: $<HTMLSelectElement>("#orb-position").value,
          size: Number($<HTMLInputElement>("#orb-size").value),
        },
      });
      feedback("Tema aplicado.");
    } catch (e) {
      feedback(String(e), true);
    }
  };
}

load()
  .then(bind)
  .catch((e) => feedback(String(e), true))
  .finally(() => {
    document.documentElement.classList.remove("loading");
  });
