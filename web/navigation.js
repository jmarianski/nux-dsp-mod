/* Browser-only navigation. Read geometry from the same far ROM and actors from
 * live P16 RAM; recreate the cached background after each successful load. */
"use strict";
class Navigation {
  constructor(canvas, program) {
    this.canvas = canvas; this.program = program;
    this.background = document.createElement("canvas");
    this.background.width = canvas.width; this.background.height = canvas.height;
    this.context = canvas.getContext("2d");
  }

  prepare(machine) {
    const address = machine.get("map_hi", 5) * 65536 + machine.get("map_lo", 5);
    const words = this.program.far.find((s) => s.addr === address).words;
    const signed = (v) => (v << 16) >> 16;
    const lines = [];
    for (let i = 0; i < words.length; i += 6)
      lines.push([...words.slice(i, i + 4).map(signed), words[i + 4] >> 8, words[i + 5]]);
    const xs = lines.flatMap((l) => [l[0], l[2]]), ys = lines.flatMap((l) => [l[1], l[3]]);
    const left = Math.min(...xs), right = Math.max(...xs), bottom = Math.min(...ys), top = Math.max(...ys);
    const {width, height} = this.canvas;
    const scale = Math.min((width - 48) / (right - left), (height - 48) / (top - bottom));
    const cx = (left + right) / 2, cy = (bottom + top) / 2;
    this.point = (x, y) => [width / 2 + (x - cx) * scale, height / 2 - (y - cy) * scale];
    const c = this.background.getContext("2d");
    c.fillStyle = "#101719"; c.fillRect(0, 0, width, height);
    // Open sector boundaries stay faint; walls and usable doors are distinct.
    for (const solid of [false, true]) for (const [x1, y1, x2, y2, action, back] of lines) {
      if ((back === 65535 || action > 0) !== solid) continue;
      c.strokeStyle = action === 255 ? "#7ce39f" : action >= 1 && action <= 4 ? "#ffce62" : solid ? "#92a5a9" : "#263337";
      c.lineWidth = action ? 3 : solid ? 1.5 : 1;
      c.beginPath(); c.moveTo(...this.point(x1, y1)); c.lineTo(...this.point(x2, y2)); c.stroke();
    }
    const route = this.program.navigation.route;
    c.strokeStyle = "#6bbcff"; c.lineWidth = 3; c.lineJoin = "round";
    c.beginPath(); route.forEach(([x, y], i) => c[i ? "lineTo" : "moveTo"](...this.point(x, y))); c.stroke();
    c.font = "14px system-ui"; c.fillStyle = "#6bbcff";
    const [x, y] = this.point(...this.program.navigation.start);
    c.fillText("START", x - 22, y + 22);
    c.fillStyle = "#ffce62";
    c.fillText("drzwi: F / D5", ...this.point(1250, -2350));
    c.fillStyle = "#a8b9bd"; c.fillText("N ↑", width - 44, 23);
  }

  draw(machine) {
    const c = this.context;
    c.drawImage(this.background, 0, 0);
    for (let i = 0; i < this.program.navigation.enemy_count; i++) {
      const state = machine.get("enemy_state", i);
      if (!(state & 127)) continue;
      const x = (machine.get("enemy_x", i) << 16) >> 16, y = (machine.get("enemy_y", i) << 16) >> 16;
      const [sx, sy] = this.point(x, y);
      c.fillStyle = "#ff726a"; c.beginPath(); c.arc(sx, sy, 5, 0, Math.PI * 2); c.fill();
      if (i === this.program.navigation.target) {
        c.strokeStyle = "#ffce62"; c.lineWidth = 2; c.beginPath(); c.arc(sx, sy, 10, 0, Math.PI * 2); c.stroke();
        c.fillStyle = "#ffce62"; c.font = "14px system-ui"; c.fillText("pierwszy żołnierz", sx - 45, sy - 18);
      }
    }
    const [px, py] = this.point((machine.get("px") << 16) >> 16, (machine.get("py") << 16) >> 16);
    c.save(); c.translate(px, py); c.rotate(-machine.get("pa") * Math.PI / 128);
    c.fillStyle = "#fff"; c.strokeStyle = "#101719"; c.lineWidth = 2;
    c.beginPath(); c.moveTo(12, 0); c.lineTo(-8, -7); c.lineTo(-4, 0); c.lineTo(-8, 7); c.closePath(); c.fill(); c.stroke(); c.restore();
  }
}
