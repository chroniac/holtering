// Шрифты локальные: закрытый контур больницы не должен обращаться к fonts.googleapis.com
import "@fontsource-variable/inter";
import "@fontsource-variable/jetbrains-mono";
import { boot } from "./app/boot";

boot().catch((e) => {
  document.getElementById("app")!.innerHTML = `<pre style="padding:20px;color:#c8102e">${String(e)}</pre>`;
});
