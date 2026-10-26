// Overrides the theme's assets/js/menu.js. Phones: the Menu dropdown is a fixed sheet under its button that scrolls
// inside the screen, and the page behind it holds still while it's open. Only a width change closes a menu: a phone
// fires resize when its address bar slides away mid-scroll, which used to shut the menu as soon as you scrolled it.
const container = document.querySelector(".container");
const allMenus = document.querySelectorAll(".menu");
const root = document.documentElement;

function place(menu) {
  const dropdown = menu.querySelector(".menu__dropdown");
  if (!menu.classList.contains("menu--mobile")) return;
  const top = Math.max(8, menu.querySelector(".menu__trigger").getBoundingClientRect().bottom + 6);
  dropdown.style.top = top + "px";
  dropdown.style.maxHeight = (window.innerHeight - top - 8) + "px";
}

function close(menu) {
  if (!menu.classList.contains("open")) return;
  menu.classList.remove("open");
  menu.querySelector(".menu__trigger").setAttribute("aria-expanded", "false");
  if (menu.classList.contains("menu--mobile")) root.classList.remove("menu-locked");
}

// Hide menus on body click
document.body.addEventListener("click", () => allMenus.forEach(close));
document.addEventListener("keydown", e => { if (e.key === "Escape") allMenus.forEach(close); });

// Close menus when the width changes (rotation, desktop resize); a height-only change re-fits the open sheet
let lastWidth = window.innerWidth;
window.addEventListener("resize", () => {
  if (window.innerWidth !== lastWidth) { lastWidth = window.innerWidth; allMenus.forEach(close); return; }
  allMenus.forEach(menu => { if (menu.classList.contains("open")) place(menu); });
});

allMenus.forEach(menu => {
  const trigger = menu.querySelector(".menu__trigger");
  const dropdown = menu.querySelector(".menu__dropdown");
  trigger.setAttribute("role", "button");
  trigger.setAttribute("tabindex", "0");
  trigger.setAttribute("aria-expanded", "false");

  function toggle(e) {
    e.stopPropagation();
    if (menu.classList.contains("open")) { close(menu); return; }
    // Close all menus before opening the current one
    allMenus.forEach(close);
    menu.classList.add("open");
    trigger.setAttribute("aria-expanded", "true");
    if (menu.classList.contains("menu--mobile")) {
      place(menu);
      dropdown.scrollTop = 0;
      root.classList.add("menu-locked");
    } else if (dropdown.getBoundingClientRect().right > container.getBoundingClientRect().right) {
      dropdown.style.left = "auto";
      dropdown.style.right = 0;
    }
  }
  trigger.addEventListener("click", toggle);
  trigger.addEventListener("keydown", e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggle(e); } });

  dropdown.addEventListener("click", e => e.stopPropagation());
});
