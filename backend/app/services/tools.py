import os
import subprocess
import shlex
import platform
from typing import List, Dict, Tuple, Optional
from pathlib import Path

IGNORE_DIRS = {'.git', '.venv', 'venv', 'node_modules', '__pycache__', '.idea', '.vscode', 'dist', 'build'}


class SystemTools:
    def _safe_path(self, current_dir: Path, target_path: str) -> Path:
        # Базовая защита от выхода за пределы (хотя для локального ассистента это опционально)
        return (current_dir / target_path).resolve()

    def list_directory(self, current_dir: Path, path: str = ".") -> str:
        try:
            target = self._safe_path(current_dir, path)
            if not target.is_dir():
                return f"Ошибка: {path} не является директорией."
            items = []
            for i in sorted(target.iterdir(), key=lambda x: (not x.is_dir(), x.name)):
                icon = "📁" if i.is_dir() else "📄"
                items.append(f"{icon} {i.name}")
            return f"Путь: {target}\n" + ("\n".join(items) if items else "Папка пуста")
        except Exception as e:
            return f"Ошибка доступа: {str(e)}"

    def read_file(self, current_dir: Path, path: str) -> str:
        try:
            target = self._safe_path(current_dir, path)
            if not target.is_file():
                return "Ошибка: Файл не найден."

            # ML-Оптимизация: ограничение на чтение слишком больших файлов
            filesize = target.stat().st_size
            if filesize > 100 * 1024:  # 100KB
                return f"Ошибка: Файл слишком большой ({filesize} байт). Используйте поиск по содержимому или терминал."

            content = target.read_text(encoding="utf-8", errors="replace")
            return content
        except Exception as e:
            return f"Ошибка чтения: {str(e)}"

    def write_file(self, current_dir: Path, path: str, content: str) -> str:
        try:
            target = self._safe_path(current_dir, path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            return f"Успех. Файл {target} обновлен."
        except Exception as e:
            return f"Ошибка записи: {str(e)}"

    def execute_command(self, current_dir: Path, command: str) -> str:
        try:
            is_windows = platform.system() == "Windows"
            # Для Windows используем shell=True, для Unix безопаснее shlex
            cmd_to_run = command if is_windows else shlex.split(command)

            result = subprocess.run(
                cmd_to_run,
                cwd=current_dir,
                capture_output=True,
                text=False,
                timeout=30,  # Сократил таймаут
                shell=is_windows
            )

            def decode_output(data: bytes) -> str:
                if not data: return ""
                for enc in ['utf-8', 'cp866', 'cp1251']:
                    try:
                        return data.decode(enc)
                    except:
                        continue
                return data.decode('utf-8', errors='replace')

            stdout = decode_output(result.stdout).strip()
            stderr = decode_output(result.stderr).strip()

            out_str = []
            if stdout: out_str.append(f"STDOUT:\n{stdout}")
            if stderr: out_str.append(f"STDERR:\n{stderr}")
            if result.returncode != 0: out_str.append(f"Код возврата: {result.returncode}")

            return "\n".join(out_str) if out_str else "Выполнено (без вывода)."
        except subprocess.TimeoutExpired:
            return "Ошибка: Превышено время ожидания."
        except Exception as e:
            return f"Ошибка запуска: {str(e)}"

    def set_working_directory(self, current_dir: Path, new_path: str) -> Tuple[str, Optional[Path]]:
        try:
            target = self._safe_path(current_dir, new_path)
            if target.is_dir():
                return f"Директория изменена на: {target}", target
            return f"Ошибка: Путь {new_path} не найден.", None
        except Exception as e:
            return f"Ошибка: {str(e)}", None

    def search_files(self, current_dir: Path, pattern: str, path: str = ".") -> str:
        try:
            target = self._safe_path(current_dir, path)
            results = [str(p.relative_to(target)) for p in target.rglob(pattern)
                       if not any(part in IGNORE_DIRS for part in p.parts)]

            if not results: return "Ничего не найдено."
            return "Найдено:\n" + "\n".join(results[:30])
        except Exception as e:
            return f"Ошибка поиска: {str(e)}"

    def get_project_tree(self, current_dir: Path, path: str = ".", max_depth: int = 3) -> str:
        try:
            target = self._safe_path(current_dir, path)
            lines = [f"📁 {target.name}"]

            def walk(d: Path, depth: int, prefix: str):
                if depth > max_depth: return
                try:
                    items = sorted(list(d.iterdir()), key=lambda x: (not x.is_dir(), x.name.lower()))
                    items = [it for it in items if it.name not in IGNORE_DIRS]
                    for i, it in enumerate(items):
                        last = (i == len(items) - 1)
                        lines.append(f"{prefix}{'└── ' if last else '├── '}{'📁' if it.is_dir() else '📄'} {it.name}")
                        if it.is_dir():
                            walk(it, depth + 1, prefix + ("    " if last else "│   "))
                except:
                    pass

            walk(target, 1, "")
            return "\n".join(lines)
        except Exception as e:
            return f"Ошибка дерева: {str(e)}"

    def find_in_files(self, current_dir: Path, text: str, path: str = ".") -> str:
        try:
            target = self._safe_path(current_dir, path)
            results = []
            for fp in target.rglob("*"):
                if fp.is_file() and not any(part in IGNORE_DIRS for part in fp.parts):
                    try:
                        c = fp.read_text(encoding="utf-8", errors="ignore")
                        if text.lower() in c.lower():
                            results.append(f"📄 {fp.relative_to(target)}")
                    except:
                        pass
            return "Найдено в файлах:\n" + "\n".join(results[:20]) if results else "Текст не найден."
        except Exception as e:
            return f"Ошибка: {str(e)}"

    @staticmethod
    def get_tool_schemas() -> List[Dict]:
        return [
            {"type": "function", "function": {"name": "list_directory", "description": "Список файлов",
                                              "parameters": {"type": "object",
                                                             "properties": {"path": {"type": "string"}}}}},
            {"type": "function", "function": {"name": "read_file", "description": "Прочитать файл полностью",
                                              "parameters": {"type": "object",
                                                             "properties": {"path": {"type": "string"}},
                                                             "required": ["path"]}}},
            {"type": "function", "function": {"name": "write_file", "description": "Записать файл (целиком!)",
                                              "parameters": {"type": "object",
                                                             "properties": {"path": {"type": "string"},
                                                                            "content": {"type": "string"}},
                                                             "required": ["path", "content"]}}},
            {"type": "function", "function": {"name": "execute_command", "description": "Выполнить команду в терминале",
                                              "parameters": {"type": "object",
                                                             "properties": {"command": {"type": "string"}},
                                                             "required": ["command"]}}},
            {"type": "function", "function": {"name": "get_project_tree", "description": "Показать дерево проекта",
                                              "parameters": {"type": "object",
                                                             "properties": {"path": {"type": "string"},
                                                                            "max_depth": {"type": "integer"}}}}},
            {"type": "function", "function": {"name": "search_files", "description": "Поиск файлов по маске",
                                              "parameters": {"type": "object",
                                                             "properties": {"pattern": {"type": "string"}},
                                                             "required": ["pattern"]}}},
            {"type": "function", "function": {"name": "find_in_files", "description": "Поиск текста внутри файлов",
                                              "parameters": {"type": "object",
                                                             "properties": {"text": {"type": "string"}},
                                                             "required": ["text"]}}},
            {"type": "function", "function": {"name": "set_working_directory", "description": "Сменить рабочую папку",
                                              "parameters": {"type": "object",
                                                             "properties": {"new_path": {"type": "string"}},
                                                             "required": ["new_path"]}}}
        ]