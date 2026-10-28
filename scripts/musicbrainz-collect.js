// Builds a MusicBrainz snapshot for data/sources/, run in a browser tab open on musicbrainz.org
// (the API is called from the page itself, at about one request per second).
//
//   1. Paste this file into the console of any https://musicbrainz.org page.
//   2. start("brandenburg", [{bwv: "1046", parts: ["<movement work MBID>", …]}, …], ["ensemble"])
//      Movement MBIDs come from the parent work: work/<id>?inc=work-rels, "parts" relations.
//   3. Watch prog.phase. When it says "done", copy(snapshot("brandenburg")) and save the text
//      as data/sources/musicbrainz-<name>.json.
//
// Progress is kept in localStorage (keys ab_<name>_*), so a closed tab can resume with start(…).
// See data/sources/README.md for the row format and the grouping rules.

const BACH = "24f1766e-9635-4d58-a4d4-9413f9f98a4c";
const wait = ms => new Promise(r => setTimeout(r, ms));
window.prog = window.prog || { phase: "idle" };
const MEM = {};
const S = {
  get(k) { if (k in MEM) return MEM[k]; const v = localStorage.getItem("ab_" + k); return v ? JSON.parse(v) : null; },
  set(k, v) { try { localStorage.setItem("ab_" + k, JSON.stringify(v)); delete MEM[k]; } catch (e) { MEM[k] = v; } },
};
window.S = S;

async function mb(path) {
  // MusicBrainz answers 503 when busy; back off and keep trying for several minutes.
  for (let i = 0; i < 20; i++) {
    let r; try { r = await fetch("/ws/2/" + path + (path.includes("?") ? "&" : "?") + "fmt=json"); } catch (e) { r = null; }
    if (r && r.ok) { await wait(1100); return r.json(); }
    if (r && r.status === 404) throw new Error("404 " + path);
    await wait(Math.min(60000, 3000 * (i + 1)));
  }
  throw new Error("MusicBrainz request failed: " + path);
}
window.mb = mb;

const GROUPS_ = ["Orchestra", "Group", "Choir"];
const yearOf = d => (d && /^\d{4}/.test(d) ? +d.slice(0, 4) : null);

// Every recording linked to one movement: who, when, live or not, first release year.
async function movement(id) {
  const w = await mb(`work/${id}?inc=recording-rels`);
  const rel = {};
  for (const r of w.relations || []) {
    if (r.type !== "performance" || !r.recording) continue;
    const ys = [yearOf(r.begin), yearOf(r.end)].filter(Boolean);
    rel[r.recording.id] = { y: ys.length ? Math.min(...ys) : null, y2: ys.length ? Math.max(...ys) : null, l: (r.attributes || []).includes("live") ? 1 : 0 };
  }
  const out = [];
  for (let off = 0; ; off += 100) {
    const b = await mb(`recording?work=${id}&inc=artist-credits&limit=100&offset=${off}`);
    for (const r of b.recordings) {
      const ac = (r["artist-credit"] || []).filter(c => c.artist.id !== BACH);
      const x = rel[r.id] || {};
      out.push([r.id, ac.map(c => c.artist.id), ac.map(c => c.name), ac.map(c => c.artist.type || ""), x.y ?? null, x.y2 ?? null, x.l || 0, yearOf(r["first-release-date"])]);
    }
    prog.phase = `${prog.set}: movement ${prog.mv}, ${out.length} of ${b["recording-count"]}`;
    if (off + 100 >= b["recording-count"]) break;
  }
  return out;
}

// Performances: same performers (Bach left out) and same year. Nearby years (up to three apart)
// with no movement in common are joined, since sets are often recorded over several sessions;
// an undated group joins the single dated performance that holds all of its movements.
function group(name) {
  const works = S.get(name + "_works");
  const recs = {};
  works.forEach((w, wi) => w.parts.forEach((p, pi) => {
    for (const row of S.get(`${name}_mv_${wi}_${pi}`) || []) {
      const [id, a, n, t, y, y2, l, f] = row;
      const e = recs[id] ||= { id, a, n, t, ys: new Set(), l: 0, f: null, mv: new Set() };
      if (y) e.ys.add(y); if (y2) e.ys.add(y2);
      e.l ||= l; if (f && (!e.f || f < e.f)) e.f = f;
      e.mv.add(`${wi}:${pi}`);
    }
  }));
  // Ensemble works credit different soloists on each concerto of one set, so they are grouped
  // by the orchestra, ensemble or choir when there is one; otherwise by everyone credited.
  const ensemble = (S.get(name + "_native") || []).includes("ensemble");
  const GROUPS = ["Orchestra", "Group", "Choir"];
  const key = r => {
    const g = ensemble ? r.a.filter((x, i) => GROUPS.includes(r.t[i])) : [];
    return (g.length ? g : r.a).slice().sort().join("+") || "?" + r.n.join("+");
  };
  const byArtist = {};
  for (const r of Object.values(recs)) (byArtist[key(r)] ||= []).push(r);
  const perfs = [];
  for (const list of Object.values(byArtist)) {
    const dated = {}, undated = [];
    for (const r of list) {
      if (r.ys.size) (dated[Math.min(...r.ys)] ||= []).push(r); else undated.push(r);
    }
    let groups = Object.entries(dated).sort((a, b) => a[0] - b[0]).map(([y, rs]) => ({ rs, ys: new Set(rs.flatMap(r => [...r.ys])), mv: new Set(rs.flatMap(r => [...r.mv])) }));
    for (let i = 1; i < groups.length; i++) {
      const a = groups[i - 1], b = groups[i];
      if (Math.min(...b.ys) - Math.max(...a.ys) <= 3 && ![...b.mv].some(m => a.mv.has(m))) {
        a.rs.push(...b.rs); b.ys.forEach(y => a.ys.add(y)); b.mv.forEach(m => a.mv.add(m));
        groups.splice(i--, 1);
      }
    }
    const undMv = new Set(undated.flatMap(r => [...r.mv]));
    const home = groups.filter(g => [...undMv].every(m => g.mv.has(m)));
    if (undated.length && home.length === 1) { home[0].rs.push(...undated); undMv.forEach(m => home[0].mv.add(m)); }
    else if (undated.length) groups.push({ rs: undated, ys: new Set(), mv: undMv });
    for (const g of groups) perfs.push(g);
  }
  return perfs.map(g => {
    const r0 = g.rs[0];
    // everyone credited anywhere in the performance: groups first, then by how often they appear
    const seen = {};
    for (const r of g.rs) r.a.forEach((id, i) => { (seen[id] ||= { id, n: r.n[i], t: r.t[i], c: 0 }).c++; });
    const people = Object.values(seen).sort((x, y) => (GROUPS_.includes(y.t) - GROUPS_.includes(x.t)) || y.c - x.c);
    const m = works.map((w, wi) => w.parts.reduce((s, p, pi) => s + (g.mv.has(`${wi}:${pi}`) ? 2 ** pi : 0), 0));
    const fs = g.rs.map(r => r.f).filter(Boolean);
    // rep: one recording of the performance, looked up for instruments, place and release
    return { n: people.map(p => p.n), a: people.map(p => p.id), t: people.map(p => p.t), y: [...g.ys].sort(), m: m.join(","), f: fs.length ? Math.min(...fs) : null, l: g.rs.some(r => r.l) ? 1 : 0, rep: r0.id, ids: g.rs.map(r => r.id) };
  });
}

// Instruments, conductor, orchestra, place and earliest release for one recording per performance.
async function detail(id) {
  const r = await mb(`recording/${id}?inc=artist-rels+place-rels+releases`);
  const ins = [], roles = {}, pl = [];
  for (const x of r.relations || []) {
    if (x["target-type"] === "artist" && x.artist) {
      if (x.type === "instrument") for (const i of x.attributes || []) { if (!ins.includes(i)) ins.push(i); roles[x.artist.name] ||= i; }
      else if (x.type === "conductor") roles[x.artist.name] = "conductor";
      else if (x.type === "performing orchestra") roles[x.artist.name] = "orchestra";
      else if (x.type === "vocal") roles[x.artist.name] ||= "voice";
    }
    if (x["target-type"] === "place" && x.place && x.type === "recorded at") pl.push(x.place.name);
  }
  const rel = (r.releases || []).filter(x => x.status === "Official" || !x.status)
    .sort((a, b) => (a.date || "9999").localeCompare(b.date || "9999"))[0] || (r.releases || [])[0];
  return { ins, roles, pl, r: rel ? [rel.id, rel.title] : null };
}

async function start(name, works, native) {
  prog.set = name;
  S.set(name + "_works", works);
  S.set(name + "_native", native);
  for (let wi = 0; wi < works.length; wi++) for (let pi = 0; pi < works[wi].parts.length; pi++) {
    const k = `${name}_mv_${wi}_${pi}`;
    if (S.get(k)) continue;
    prog.mv = `${works[wi].bwv}/${pi + 1}`;
    S.set(k, await movement(works[wi].parts[pi]));
  }
  const perfs = group(name);
  const det = S.get(name + "_det") || {};
  let n = 0;
  for (const p of perfs) {
    n++;
    if (det[p.rep]) continue;
    prog.phase = `${name}: details ${n} of ${perfs.length}`;
    det[p.rep] = await detail(p.rep);
    if (n % 10 === 0) S.set(name + "_det", det);
  }
  S.set(name + "_det", det);
  prog.phase = "done";
}

// The rows of data/sources/musicbrainz-<name>.json, keys as in its README.
function rows(name) {
  const det = S.get(name + "_det") || {};
  return group(name).map(p => {
    const d = det[p.rep] || {};
    const row = { n: p.n, a: p.a, y: p.y, m: p.m };
    if (p.t.some(Boolean)) row.t = p.t;
    if (p.f) row.f = p.f;
    if (p.l) row.l = 1;
    if (d.ins && d.ins.length) row.ins = d.ins;
    if (d.roles && Object.keys(d.roles).length) row.roles = d.roles;
    if (d.pl && d.pl.length) row.pl = d.pl;
    if (d.r) row.r = d.r;
    row.rep = p.rep;
    return row;
  }).sort((a, b) => (a.a[0] || "").localeCompare(b.a[0] || "") || ((a.y[0] || 9999) - (b.y[0] || 9999)));
}

function snapshot(name) {
  const works = S.get(name + "_works");
  return '{\n"works": ' + JSON.stringify(works.map(w => w.bwv)) + ',\n"native": ' + JSON.stringify(S.get(name + "_native")) +
    ',\n"rows": [\n' + rows(name).map(r => JSON.stringify(r)).join(",\n") + "\n]\n}\n";
}

// Checksum per row, for comparing a copy against the page (djb2, xor variant, unsigned).
function cleanH(s) { let h = 5381; for (const c of s) h = ((h * 33) ^ c.codePointAt(0)) >>> 0; return h; }

Object.assign(window, { movement, group, detail, start, rows, snapshot, cleanH });
