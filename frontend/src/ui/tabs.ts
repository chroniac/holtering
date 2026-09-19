import { el } from "./dom";

export const tabs = <T extends string>(
  items: [T, string][],
  initial: T,
  onPick: (t: T) => void,
): { root: HTMLElement; set(t: T): void; label(t: T, s: string): void } => {
  const root = el("div", "tabs");
  const btns: Record<string, HTMLElement> = {};
  for (const [id, label] of items) {
    const b = el("button", `tab${id === initial ? " on" : ""}`, label);
    b.addEventListener("click", () => onPick(id));
    btns[id] = b;
    root.append(b);
  }
  return {
    root,
    set(t) {
      for (const [k, b] of Object.entries(btns)) b.classList.toggle("on", k === t);
    },
    label(t, s) {
      btns[t].textContent = s;
    },
  };
};
