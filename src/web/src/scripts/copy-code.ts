/** Adds a copy button to every code block inside a `[data-copyable]` container. */
const COPY = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="size-3.5"><rect width="14" height="14" x="8" y="8" rx="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/></svg>`;
const CHECK = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="size-3.5 text-success"><path d="M20 6 9 17l-5-5"/></svg>`;

for (const pre of document.querySelectorAll<HTMLPreElement>("[data-copyable] pre")) {
  const wrapper = document.createElement("div");
  wrapper.className = "group/code relative";
  pre.replaceWith(wrapper);
  wrapper.append(pre);

  const button = document.createElement("button");
  button.type = "button";
  button.setAttribute("aria-label", "Copy to clipboard");
  button.className =
    "absolute top-2 right-2 inline-flex size-7 items-center justify-center rounded-md border bg-background/80 text-muted-foreground opacity-0 backdrop-blur transition hover:text-foreground focus-visible:opacity-100 group-hover/code:opacity-100 pointer-coarse:opacity-100";
  button.innerHTML = COPY;
  button.addEventListener("click", async () => {
    await navigator.clipboard.writeText(pre.innerText);
    button.innerHTML = CHECK;
    setTimeout(() => (button.innerHTML = COPY), 1500);
  });
  wrapper.append(button);
}
