// A suggestion fills the box, so the question can still be edited. Nothing is sent until asked.
(function () {
  var form = document.getElementById("ask-form");
  if (!form) { return; }
  var box = form.querySelector("textarea");

  document.querySelectorAll("[data-suggest]").forEach(function (button) {
    button.addEventListener("click", function () {
      box.value = button.dataset.suggest;
      box.focus();
    });
  });

  box.addEventListener("keydown", function (event) {
    if (event.key === "Enter" && !event.shiftKey && box.value.trim()) {
      event.preventDefault();
      form.requestSubmit();
    }
  });
})();
