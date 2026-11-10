// The scorecard's Alpine component (scorecard design "The Alpine component").
// It only adds behaviour to a page the server rendered in full: the Before/After
// toggle, room selection, the evidence scope, replay and live lines. Data is read
// from #sc-data with JSON.parse and shown with x-text bindings only.
document.addEventListener("alpine:init", function () {
  document.documentElement.classList.add("js");
});

function scorecard() {
  var el = document.getElementById("sc-data");
  var data = el ? JSON.parse(el.textContent) : {};
  var reduced = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  return {
    view: "before",
    room: data.defaultRoom || "",
    logScope: "room",
    replaying: false,
    shown: 0,
    live: false,
    liveLines: [],
    verdictReady: false,
    announce: "",
    busy: false,
    error: "",
    _seen: {},
    _pending: 0,
    _lastAnnounce: 0,

    init: function () {
      var self = this;
      (data.seenIds || []).forEach(function (id) { self._seen[id] = true; });
      if (data.streamUrl && window.EventSource) {
        this.live = true;
        var es = new EventSource(data.streamUrl);
        es.addEventListener("fact", function (ev) {
          var line;
          try { line = JSON.parse(ev.data); } catch (e) { return; }
          if (!line || self._seen[line.fact_id]) return;
          self._seen[line.fact_id] = true;
          self.liveLines.push(line);
          self._pending += 1;
          self._announce();
        });
        es.addEventListener("finalized", function () { self.verdictReady = true; });
        es.addEventListener("done", function () { es.close(); self.live = false; });
      }
    },

    _announce: function () {
      var self = this;
      var now = Date.now();
      if (now - this._lastAnnounce < 5000) {
        if (!this._timer) {
          this._timer = setTimeout(function () { self._timer = null; self._announce(); }, 5000);
        }
        return;
      }
      this._lastAnnounce = now;
      this.announce = this._pending + " new facts";
      this._pending = 0;
    },

    inScope: function (node) {
      return this.logScope === "all" || node.dataset.room === this.room;
    },

    visibleLine: function (node) {
      return this.inScope(node) && (!this.replaying || Number(node.dataset.idx) < this.shown);
    },

    replay: function () {
      var gaps = data.replayGaps || [];
      var self = this;
      if (reduced || !gaps.length) { this.replaying = false; return; }
      this.replaying = true;
      this.shown = 0;
      var i = 0;
      var step = function () {
        self.shown = i + 1;
        i += 1;
        if (i >= gaps.length) { self.replaying = false; return; }
        setTimeout(step, gaps[i]);
      };
      setTimeout(step, 0);
    },

    generate: function () {
      var self = this;
      this.busy = true;
      fetch("/runs/" + encodeURIComponent(data.runId || "") + "/exorcise", { method: "POST" })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (body) {
          if (body && typeof body.report_url === "string" && body.report_url.indexOf("/exorcisms/") === 0) {
            window.location.assign(body.report_url);
          } else {
            self.busy = false;
            self.error = "Request refused.";
          }
        })
        .catch(function () { self.busy = false; self.error = "Request failed."; });
    },

    launch: function (room) {
      var self = this;
      this.busy = true;
      this.error = "";
      fetch("/exorcist/demo", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ room: room })
      }).then(function (r) {
        if (!r.ok) { self.error = "Request refused (" + r.status + ")."; self.busy = false; return null; }
        return r.json();
      }).then(function (body) {
        if (body && typeof body.report_url === "string" && body.report_url.indexOf("/exorcisms/") === 0) {
          window.location.assign(body.report_url);
        } else if (body) {
          self.busy = false;
        }
      }).catch(function () {
        self.error = "Request failed.";
        self.busy = false;
      });
    }
  };
}
