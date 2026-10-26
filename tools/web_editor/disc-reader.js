/* Reads the two files the editor needs (SLUS_014.11 and DATA/WA_MRG.MRG)
 * straight out of the player's disc image, a piece at a time, so the whole
 * 500 MB .bin never has to sit in memory. The same reading as the editor's
 * disc.py (DiscImage): raw 2352-byte sectors (data at +24 or +16) or a
 * 2048-byte ISO, through the ISO 9660 directories. */
(function (root) {
  "use strict";

  const FORMATS = [[2352, 24], [2352, 16], [2048, 0]];
  const CHUNK = 512; // sectors read at a time

  async function bytesOf(blob, start, end) {
    return new Uint8Array(await blob.slice(start, end).arrayBuffer());
  }

  function u32(data, at) {
    return (data[at] | (data[at + 1] << 8) | (data[at + 2] << 16) | (data[at + 3] << 24)) >>> 0;
  }

  async function open(file) {
    for (const [sector, skip] of FORMATS) {
      if (file.size % sector || file.size < 17 * sector) continue;
      const head = await bytesOf(file, 16 * sector + skip, 16 * sector + skip + 2048);
      if (String.fromCharCode(...head.subarray(1, 6)) === "CD001") return { file, sector, skip };
    }
    throw new Error("That file is not a CD image the editor can read. Choose the .bin of your .bin/.cue pair.");
  }

  /* `size` bytes from sector `lba` on, the sector headers left out. */
  async function read(disc, lba, size, progress) {
    const sectors = Math.ceil(size / 2048);
    const out = new Uint8Array(sectors * 2048);
    for (let done = 0; done < sectors; done += CHUNK) {
      const count = Math.min(CHUNK, sectors - done);
      const start = (lba + done) * disc.sector;
      const raw = await bytesOf(disc.file, start, start + count * disc.sector);
      if (raw.length < count * disc.sector) throw new Error("The disc image ends early; it may be incomplete.");
      if (disc.sector === 2048) out.set(raw, done * 2048);
      else for (let i = 0; i < count; i++) {
        out.set(raw.subarray(i * disc.sector + disc.skip, i * disc.sector + disc.skip + 2048), (done + i) * 2048);
      }
      if (progress) progress(Math.min(1, (done + count) / sectors));
    }
    return out.subarray(0, size);
  }

  function* directory(data) {
    let at = 0;
    while (at < data.length) {
      const record = data[at];
      if (!record) { at = (Math.floor(at / 2048) + 1) * 2048; continue; }
      const nameLength = data[at + 32];
      const name = String.fromCharCode(...data.subarray(at + 33, at + 33 + nameLength)).split(";")[0].toUpperCase();
      yield { name, lba: u32(data, at + 2), size: u32(data, at + 10), dir: (data[at + 25] & 2) !== 0 };
      at += record;
    }
  }

  async function find(disc, path) {
    const pvd = await read(disc, 16, 2048);
    let lba = u32(pvd, 156 + 2), length = u32(pvd, 156 + 10);
    const parts = path.split("/").filter(Boolean).map((p) => p.toUpperCase());
    for (let i = 0; i < parts.length; i++) {
      let next = null;
      for (const entry of directory(await read(disc, lba, length))) {
        if (entry.name === parts[i]) { next = entry; break; }
      }
      if (!next) return null;
      if (i === parts.length - 1) return next;
      if (!next.dir) return null;
      lba = next.lba; length = next.size;
    }
    return null;
  }

  /* {slus, wa}: the two files, as Uint8Arrays. */
  async function gameFiles(file, progress) {
    const disc = await open(file);
    const slus = await find(disc, "SLUS_014.11");
    const wa = await find(disc, "DATA/WA_MRG.MRG");
    if (!slus || !wa) {
      throw new Error("That disc image is not Yu-Gi-Oh! Forbidden Memories (USA, SLUS-01411).");
    }
    const slusData = await read(disc, slus.lba, slus.size);
    const waData = await read(disc, wa.lba, wa.size, progress);
    return { slus: slusData, wa: waData };
  }

  root.DiscReader = { gameFiles };
})(globalThis);
