import json
import subprocess
import shlex
import platform
import urllib
from typing import List, Dict, Tuple, Optional
from pathlib import Path

IGNORE_DIRS = {'.git', '.venv', 'venv', 'node_modules', '__pycache__', '.idea', '.vscode'}


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
            if filesize > 10240 * 1024:
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
                timeout=300,  # Сократил таймаут
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

    def get_system_info(self, current_dir: Path) -> str:
        """Собирает информацию о системе, дисках и сетевых хранилищах."""
        info = [f"ОС: {platform.system()} {platform.release()} ({platform.machine()})"]

        try:
            if platform.system() == "Windows":
                # Получаем логические и сетевые диски в Windows
                drives = subprocess.check_output(
                    "wmic logicaldisk get name, description, providername",
                    shell=True, text=True, errors="replace"
                )
                net_use = subprocess.check_output(
                    "net use", shell=True, text=True, errors="replace"
                )
                info.append("=== Диски и сетевые пути ==\n" + drives.strip())
                info.append("=== Сетевые подключения (net use) ==\n" + net_use.strip())
            else:
                # В Linux/macOS смотрим примонтированные диски
                df_out = subprocess.check_output(["df", "-h"], text=True, errors="replace")
                info.append("=== Примонтированные диски (df -h) ==\n" + df_out.strip())
        except Exception as e:
            info.append(f"Ошибка получения инфо о дисках: {str(e)}")

        return "\n\n".join(info)

    def patch_file(self, current_dir: Path, path: str, search_text: str, replace_text: str) -> str:
        """Точечная замена текста в файле."""
        try:
            target = self._safe_path(current_dir, path)
            if not target.is_file():
                return f"Ошибка: Файл {path} не найден."

            content = target.read_text(encoding="utf-8", errors="replace")

            if search_text not in content:
                return "Ошибка: Искомый текст (search_text) не найден в файле. Убедитесь, что скопировали его символ в символ."

            occurrences = content.count(search_text)
            if occurrences > 1:
                return f"Ошибка: Искомый текст встречается {occurrences} раз. Сделайте search_text более уникальным, захватив соседние строки."

            new_content = content.replace(search_text, replace_text)
            target.write_text(new_content, encoding="utf-8")
            return f"Успех. Файл {path} пропатчен. Заменено {len(search_text)} символов на {len(replace_text)} символов."
        except Exception as e:
            return f"Ошибка патчинга: {str(e)}"

    def fetch_web_page(self, current_dir: Path, url: str) -> str:
        """Простой GET-запрос для чтения сайтов/API агентом."""
        try:
            req = urllib.request.Request(
                url,
                headers={'User-Agent': 'Mozilla/5.0 (AI Agent; DeepSeek-671b)'}
            )
            with urllib.request.urlopen(req, timeout=15) as response:
                content_type = response.headers.get_content_type()
                charset = response.info().get_param('charset', 'utf-8')
                data = response.read().decode(charset, errors='replace')

                if content_type == 'application/json':
                    # Красиво форматируем JSON
                    try:
                        return json.dumps(json.loads(data), indent=2, ensure_ascii=False)
                    except:
                        pass

                # Ограничиваем размер (чтобы не забить контекст 10 МБ HTML-кода)
                if len(data) > 50000:
                    return f"Текст слишком большой ({len(data)} символов). Первые 50000 символов:\n\n" + data[:50000]
                return data
        except Exception as e:
            return f"Ошибка скачивания {url}: {str(e)}"


    @staticmethod
    def get_tool_schemas() -> List[Dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "execute_command",
                    "description": (
                        "Выполняет произвольную команду в системном терминале (shell). "
                        "ОЧЕНЬ ВАЖНО: Команды должны быть неинтерактивными! Не используйте vim, nano, less, top, или скрипты, ожидающие ввода пользователя (Y/n). "
                        "Если команда может потребовать подтверждения, используйте флаги вроде -y. "
                        "Состояние (например, команда `cd`) не сохраняется между вызовами! Используйте инструмент set_working_directory для смены папки. "
                        "Можно использовать пайпы (|) и перенаправления (>, >>)."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "command": {
                                "type": "string",
                                "description": "Shell-команда для выполнения (например: 'npm run build', 'pytest', 'git status', 'grep -r \"FIXME\" .')."
                            }
                        },
                        "required": ["command"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "write_file",
                    "description": (
                        "Создает новый файл или ПОЛНОСТЬЮ перезаписывает существующий. "
                        "ВНИМАНИЕ: Вы передаете полное содержимое файла. Если файл большой и вам нужно изменить лишь пару строк, "
                        "лучше используйте execute_command с утилитами sed/awk или запишите скрипт для изменения. "
                        "Отсутствующие директории в пути будут созданы автоматически."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {
                                "type": "string",
                                "description": "Относительный или абсолютный путь к файлу (например, 'src/main.py')."
                            },
                            "content": {
                                "type": "string",
                                "description": "Полный исходный код или текст для записи в файл."
                            }
                        },
                        "required": ["path", "content"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "read_file",
                    "description": (
                        "Читает содержимое файла целиком. "
                        "Используйте для изучения исходного кода, логов или конфигураций. "
                        "Имеется лимит на размер (около 10 МБ). Для очень больших файлов используйте терминал (execute_command с head, tail или grep)."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {
                                "type": "string",
                                "description": "Путь к файлу, который нужно прочитать (например, 'requirements.txt')."
                            }
                        },
                        "required": ["path"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "get_project_tree",
                    "description": (
                        "Возвращает иерархическое дерево файлов и папок проекта. "
                        "Идеально подходит для первичного ознакомления с архитектурой неизвестного репозитория. "
                        "Системные папки (.git, node_modules, venv) скрыты по умолчанию."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {
                                "type": "string",
                                "description": "Корневая директория для построения дерева. По умолчанию текущая ('.')."
                            },
                            "max_depth": {
                                "type": "integer",
                                "description": "Максимальная глубина вложенности. Увеличьте (например, до 5-6), если проект большой. По умолчанию 3."
                            }
                        }
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "search_files",
                    "description": "Ищет файлы по названию или маске (glob pattern) во всех вложенных папках.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "pattern": {
                                "type": "string",
                                "description": "Маска поиска (например, '*.py', 'docker-compose*.yml', '*config*')."
                            },
                            "path": {
                                "type": "string",
                                "description": "Папка, с которой начать поиск (по умолчанию '.')."
                            }
                        },
                        "required": ["pattern"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "find_in_files",
                    "description": (
                        "Полнотекстовый поиск подстроки по всем файлам в проекте. "
                        "Полезно для поиска объявлений функций, классов, использования переменных или текстов ошибок."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "text": {
                                "type": "string",
                                "description": "Текст или фрагмент кода для поиска (без учета регистра)."
                            },
                            "path": {
                                "type": "string",
                                "description": "Папка для ограничения зоны поиска (по умолчанию '.')."
                            }
                        },
                        "required": ["text"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "list_directory",
                    "description": "Показывает список файлов и папок только на одном (текущем) уровне. Менее информативно, чем get_project_tree, но работает быстрее для плоских папок.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {
                                "type": "string",
                                "description": "Путь к директории (по умолчанию '.')."
                            }
                        }
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "set_working_directory",
                    "description": (
                        "Глобально меняет текущую рабочую директорию (CWD) для ИИ агента. "
                        "Все последующие вызовы execute_command, read_file и другие будут выполняться относительно этого нового пути."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "new_path": {
                                "type": "string",
                                "description": "Абсолютный или относительный путь к новой рабочей директории."
                            }
                        },
                        "required": ["new_path"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "get_system_info",
                    "description": (
                        "Возвращает информацию об операционной системе, а также список всех дисков, "
                        "включая локальные, сетевые (Network Drives) и USB-накопители. "
                        "Используй это, если пользователь просит найти флешку, сетевой диск или узнать ОС."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {}
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "patch_file",
                    "description": (
                        "Используй для изменения существующего файла без его полного переписывания (идеально для изменения 1-2 строк в большом коде). "
                        "Ищет точное совпадение строки search_text и меняет её на replace_text. "
                        "ВАЖНО: search_text должен быть достаточно большим (включать соседние строки), чтобы быть уникальным в файле."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {
                                "type": "string",
                                "description": "Путь к файлу."
                            },
                            "search_text": {
                                "type": "string",
                                "description": "Оригинальный текст из файла, который нужно заменить. Должен совпадать 1 в 1, включая пробелы и табы."
                            },
                            "replace_text": {
                                "type": "string",
                                "description": "Новый текст, который будет вставлен вместо search_text."
                            }
                        },
                        "required": ["path", "search_text", "replace_text"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "fetch_web_page",
                    "description": (
                        "Скачивает текстовое содержимое по URL-адресу (HTML, JSON, текст). "
                        "Полезно, если тебе нужно прочитать документацию в интернете, посмотреть ответ API или скачать внешний скрипт."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "url": {
                                "type": "string",
                                "description": "URL-адрес, начинающийся с http:// или https://"
                            }
                        },
                        "required": ["url"]
                    }
                }
            }
        ]