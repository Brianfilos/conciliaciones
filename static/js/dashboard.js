// Auto-submit per_page select (already inline, but keep as fallback)
document.addEventListener("DOMContentLoaded", function () {
  // Highlight active tab button based on URL param
  var params = new URLSearchParams(window.location.search);
  var currentTab = params.get("tab") || "encabezado";
  document.querySelectorAll(".tab-btn").forEach(function (btn) {
    if (btn.dataset.tab === currentTab) {
      btn.classList.add("active");
    } else {
      btn.classList.remove("active");
    }
  });

  // Submit filter form on Enter in text/date inputs
  var form = document.getElementById("filter-form");
  if (form) {
    form.querySelectorAll("input[type=text], input[type=date]").forEach(function (inp) {
      inp.addEventListener("keydown", function (e) {
        if (e.key === "Enter") { e.preventDefault(); form.submit(); }
      });
    });
  }
});
