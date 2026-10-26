/* Fill case study numbers from data/stats.json so the page never drifts from the pipeline. */
(function () {
  "use strict";
  var $ = function (id) { return document.getElementById(id); };
  var fmt = function (n) { return Math.round(n).toLocaleString("en-US"); };
  fetch("data/stats.json").then(function (r) { return r.json(); }).then(function (s) {
    var status = s.validation_status;
    var reviewer = { owner: "by hand review", claude_accepted: "by Claude's review of image chips" }[status] ||
      "(provisional review)";
    $("t-flagged").textContent = fmt(s.n_flagged);
    $("lede").textContent = "ParcelWatch compared " + s.before_year + " and " + s.after_year +
      " aerial imagery over " + s.area_km2 + " km² of east Wake County, NC. " + fmt(s.n_flagged) +
      " parcels show building change with no permit on file, adding about " +
      fmt(s.added_sqft_flagged) + " sq ft.";
    if (s.precision === null) {
      $("t-precision").textContent = "Pending";
      $("t-tax").textContent = "Pending";
      $("t-tax-note").textContent = "shown after validation";
      return;
    }
    var pct = Math.round(s.precision * 100);
    $("t-precision").textContent = pct + "%";
    $("t-precision-note").textContent = s.validation_tp + " of " + s.validation_n_flagged +
      " flags confirmed " + reviewer;
    $("t-tax").textContent = "$" + fmt(s.est_yearly_tax_usd_adjusted);
    $("t-tax-note").textContent = "per year, adjusted for " + pct + "% precision";
    $("acc-text").textContent = s.validation_tp + " of " + s.validation_n_flagged +
      " flags were confirmed as real building change. In the unchanged sample, the miss rate was " +
      Math.round(s.miss_rate * 100) + "%." + ({
        claude_accepted: " Labels come from Claude's blind review of before/after image chips, accepted by " +
          "the owner; they are not a field check.",
        claude_provisional: " These labels are a provisional review and are being re-checked by hand."
      }[status] || "");
    $("money-text").textContent = "Value per sq ft: $" + s.value_per_sqft.toFixed(2) +
      ". Tax year " + s.tax_year + " rates. Estimated missed tax: $" +
      fmt(s.est_yearly_tax_usd_adjusted) + " per year after multiplying by " + pct +
      "% precision. Fire district tax is left out, so the figure is conservative.";
    var c = s.confusion;
    if (c) {
      $("confusion").hidden = false;
      $("c-tp").textContent = c.tp; $("c-fp").textContent = c.fp;
      $("c-fn").textContent = c.fn; $("c-tn").textContent = c.tn;
    }
    var names = { new: "New building", expanded: "Expanded", new_and_expanded: "New and expanded",
      demolished_only: "Demolished only" };
    var bc = s.precision_by_claim || {};
    var claimRows = Object.keys(bc).map(function (k) {
      var r = bc[k];
      return "<tr><td>" + names[k] + '</td><td class="num mono">' + r.n + '</td><td class="num mono">' +
        r.confirmed + '</td><td class="num mono">' + Math.round(100 * r.confirmed / r.n) + "%</td></tr>";
    });
    if (claimRows.length) {
      $("by-claim").hidden = false;
      $("by-claim").querySelector("tbody").innerHTML = claimRows.join("");
    }
    var causes = Object.entries(s.false_alarm_causes || {}).sort(function (a, b) { return b[1] - a[1]; });
    if (causes.length) {
      var max = causes[0][1];
      $("causes").innerHTML = causes.map(function (kv) {
        return '<div class="bar"><span>' + kv[0].replace(/_/g, " ") + '</span><i style="width:' +
          (100 * kv[1] / max) + '%"></i><span class="mono">' + kv[1] + "</span></div>";
      }).join("");
    }
  });
})();
