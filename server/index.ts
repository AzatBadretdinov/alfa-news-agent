import { createApplication } from "./app.js";
import { loadSettings } from "./config.js";

const settings = loadSettings();

console.log("Подготовка базы данных.");

const runtime = await createApplication(settings);
const server = runtime.app.listen(settings.port, settings.host, () =>
  console.log(
    "Откройте http://localhost:" +
      settings.port +
      " | режим: " +
      settings.mode +
      " | Node.js",
  ),
);

server.on("error", async (error: NodeJS.ErrnoException) => {
  console.error(
    error.code === "EADDRINUSE"
      ? "Порт уже занят. Остановите прежний сервер или измените PORT в .env."
      : "Не удалось запустить сервер: " + error.code,
  );
  await runtime.close();
  process.exitCode = 1;
});

let stopping = false;
for (const signal of ["SIGINT", "SIGTERM"] as const)
  process.on(signal, () => {
    if (stopping) return;
    stopping = true;
    server.close(() => {
      void runtime.close().then(() => {
        process.exitCode = 0;
      });
    });
  });
