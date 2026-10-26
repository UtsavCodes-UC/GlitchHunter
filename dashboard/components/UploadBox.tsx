"use client";
import { useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { uploadFiles } from "@/lib/api";
import { Busy, ErrorBox } from "@/components/ui";

type FileWithPath = File & { webkitRelativePath?: string };

// Dropped folders arrive as directory entries: walk them and read every file (the relative path is kept as the file name).
async function walk(entry: FileSystemEntry, prefix: string, out: File[]): Promise<void> {
  if (entry.isFile) {
    const file = await new Promise<File>((res, rej) => (entry as FileSystemFileEntry).file(res, rej));
    Object.defineProperty(file, "webkitRelativePath", { value: prefix + entry.name });
    out.push(file);
  } else if (entry.isDirectory) {
    const reader = (entry as FileSystemDirectoryEntry).createReader();
    for (;;) {
      const batch = await new Promise<FileSystemEntry[]>((res, rej) => reader.readEntries(res, rej));
      if (!batch.length) break;
      for (const e of batch) {
        if (["node_modules", ".git", "venv", ".venv", "__pycache__"].includes(e.name)) continue;   // never worth reading
        await walk(e, `${prefix}${entry.name}/`, out);
      }
    }
  }
}

export default function UploadBox() {
  const router = useRouter();
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [over, setOver] = useState(false);
  const [sent, setSent] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const filesRef = useRef<HTMLInputElement>(null);
  const folderRef = useRef<HTMLInputElement>(null);

  async function send(files: File[]) {
    if (!files.length) return;
    setBusy(true); setError(null); setSent(files.length);
    try { const p = await uploadFiles(files, name); router.push(`/project?id=${p.id}`); }
    catch (e) { setError((e as Error).message); setBusy(false); setSent(0); }
  }

  async function onDrop(e: React.DragEvent) {
    e.preventDefault(); setOver(false);
    const items = Array.from(e.dataTransfer.items ?? []);
    const entries = items.map((i) => i.webkitGetAsEntry?.()).filter(Boolean) as FileSystemEntry[];
    if (entries.some((en) => en.isDirectory)) {
      const out: File[] = [];
      try { for (const en of entries) await walk(en, "", out); } catch { setError("Could not read the dropped folder."); return; }
      await send(out);
    } else await send(Array.from(e.dataTransfer.files));
  }

  return (
    <div className={`own ${over ? "over" : ""}`} id="upload-box" role="group" aria-label="Upload your own code"
      onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)} onDrop={onDrop}>
      <p>
        Drop a <b>.zip</b> of a FastAPI + PostgreSQL project here, or pick files or a folder. We read it first without running anything and point out endpoints that look like read-check-write.
        Running it comes after you fill in a short setup.
      </p>
      <div className="row">
        <input className="plain" type="text" value={name} onChange={(e) => setName(e.target.value)} placeholder="project name (optional)" aria-label="Project name" maxLength={60} disabled={busy} />
        <button disabled={busy} onClick={() => filesRef.current?.click()}>Choose zip or files</button>
        <button disabled={busy} onClick={() => folderRef.current?.click()}>Choose a folder</button>
        {busy && <Busy text={sent ? `Uploaded ${sent} file${sent === 1 ? "" : "s"}. Reading the code…` : "Reading the files…"} />}
      </div>
      <p className="fine">
        Up to 3 MB zipped. Only source and text files are kept (.py, .sql, .txt, .md, .json, .yaml, .toml, .cfg, .ini); venv, .git and node_modules are skipped.
        Your code later runs on this machine in its own process with its own database role and none of our API keys, but it can reach the internet.
        Don&apos;t upload code you don&apos;t trust, or anything that holds real secrets.
      </p>
      <input ref={filesRef} type="file" multiple hidden onChange={(e) => { void send(Array.from(e.target.files ?? [])); e.target.value = ""; }} />
      <input ref={folderRef} type="file" hidden {...({ webkitdirectory: "", directory: "" } as Record<string, string>)}
        onChange={(e) => { void send(Array.from(e.target.files ?? []) as FileWithPath[]); e.target.value = ""; }} />
      <ErrorBox message={error} />
    </div>
  );
}
