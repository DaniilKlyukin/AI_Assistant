import json
import logging
import re
from pathlib import Path
from typing import List, Dict, Tuple, Optional
from litellm import acompletion
from app.core.config import settings
from app.services.tools import SystemTools

logger = logging.getLogger(__name__)


class AIAgent:
    def __init__(self):
        self.model = settings.MODEL
        self.api_base = settings.API_BASE
        self.tools = SystemTools()

        self._tool_map = {
            "list_directory": self.tools.list_directory,
            "read_file": self.tools.read_file,
            "write_file": self.tools.write_file,
            "execute_command": self.tools.execute_command,
            "set_working_directory": self.tools.set_working_directory,
            "search_files": self.tools.search_files,
            "get_project_tree": self.tools.get_project_tree,
            "find_in_files": self.tools.find_in_files,
            "get_system_info": self.tools.get_system_info,
            "patch_file": self.tools.patch_file,
            "fetch_web_page": self.tools.fetch_web_page,
        }

    def _prepare_message_for_db(self, msg_obj) -> Dict:
        if hasattr(msg_obj, "model_dump"):
            msg_dict = msg_obj.model_dump(exclude_none=True)
        else:
            msg_dict = msg_obj
        allowed_keys = {"role", "content", "tool_calls", "tool_call_id", "name"}
        return {k: v for k, v in msg_dict.items() if k in allowed_keys}

    async def run_cycle(self, user_input: str, history: List[Dict], current_dir: Path,
                        temperature: float = 0.3, top_p: float = 0.8, max_iterations: int = 20) -> Tuple[
        str, List[Dict], Optional[Path]]:
        new_dir = None
        new_messages = []
        full_path = current_dir.resolve()

        # Список для хранения подробностей выполненных действий
        executed_actions_report = []

        system_prompt = (
            """Ты — автономный ИИ-агент, работающий в операционной системе пользователя. 
            Твоя задача: эффективно и безопасно выполнять задания по программированию, администрированию и управлению файлами.

            ### ДОСТУПНЫЕ ИНСТРУМЕНТЫ:
            Тебе доступны следующие функции для взаимодействия с системой:
            1. list_directory(path): Список файлов в папке.
            2. read_file(path): Чтение содержимого файла.
            3. write_file(path, content): Запись файла (полная перезапись содержимого).
            4. execute_command(command): Выполнение команд в терминале.
            5. get_project_tree(path, max_depth): Визуализация структуры проекта.
            6. search_files(pattern): Поиск файлов по названию (маске).
            7. find_in_files(text): Поиск строки текста внутри всех файлов.
            8. set_working_directory(new_path): Смена текущей рабочей директории.

            ### ПРАВИЛА РАБОТЫ:
            1. Действуй напрямую: Никаких долгих размышлений.
            2. Безопасность: Перед изменением файла всегда читай его.
            3. Целостность данных: Передавай файл целиком.
            4. ВЫЗОВ ИНСТРУМЕНТОВ: Ты ДОЛЖЕН использовать нативный механизм вызова функций (Tool Calling API). КАТЕГОРИЧЕСКИ ЗАПРЕЩАЕТСЯ писать JSON вроде обычным текстом в ответе!
            5. ЭКРАНИРОВАНИЕ: При вызове execute_command внутри аргумента command ВСЕГДА используй ОДИНАРНЫЕ кавычки ('), а не двойные ("), чтобы не сломать JSON-формат. Пути в Windows пиши с двойными слэшами (C:\\folder).

            ### ФОРМАТ ОТВЕТА:
            - Для действий: Вызывай инструменты ТОЛЬКО через системный механизм (Tool Calling API). НЕ пиши JSON вызова инструмента в основном тексте ответа!
            - Для общения: После выполнения всех необходимых действий (или если действия не требуются), напиши краткий и понятный комментарий о проделанной работе.

            Будь точен, краток и профессионален. Начинай работу."""
        )

        messages = [{"role": "system", "content": system_prompt}] + history
        if user_input:
            messages.append({"role": "user", "content": user_input})

        executed_tools_history = set()

        for i in range(max_iterations):
            logger.info(f"Итерация {i + 1}/{max_iterations}")

            response = await acompletion(
                model=self.model,
                messages=messages,
                tools=self.tools.get_tool_schemas(),
                api_base=self.api_base,
                api_key=settings.OLLAMA_API_KEY,
                temperature=temperature,
                top_p=top_p
            )

            resp_obj = response.choices[0].message
            if resp_obj.content and str(resp_obj.content).strip() == "{}":
                resp_obj.content = None

            # Сначала конвертируем ответ в словарь, чтобы мы могли его изменять
            msg_dict = resp_obj.model_dump(exclude_none=True)

            # ЖЕЛЕЗОБЕТОННАЯ ОБРАБОТКА ГАЛЛЮЦИНАЦИЙ: перехватываем JSON, если ИИ написал его текстом
            if not msg_dict.get("tool_calls") and msg_dict.get("content"):
                content_str = msg_dict["content"]

                # Функция для надежного извлечения JSON с учетом вложенности скобок
                def extract_tool_json(text: str) -> Optional[Tuple[str, dict]]:
                    start_idx = text.find('{')
                    while start_idx != -1:
                        count = 0
                        found_match = False

                        for i in range(start_idx, len(text)):
                            if text[i] == '{':
                                count += 1
                            elif text[i] == '}':
                                count -= 1

                            if count == 0:  # Нашли закрывающую скобку главного объекта
                                json_str = text[start_idx:i + 1]
                                try:
                                    parsed = json.loads(json_str)

                                    # Формат 1: Обычный вызов
                                    if "name" in parsed and "arguments" in parsed:
                                        return json_str, parsed

                                    # Формат 2: Строгий формат OpenAI/DeepSeek
                                    if "function" in parsed and isinstance(parsed["function"], dict):
                                        func_data = parsed["function"]
                                        if "name" in func_data and "arguments" in func_data:
                                            return json_str, func_data

                                except json.JSONDecodeError:
                                    # --- РЕЖИМ СПАСЕНИЯ БИТОГО JSON ---
                                    # Срабатывает, если ИИ забыл экранировать кавычки или слэши Windows
                                    name_match = re.search(r'"name"\s*:\s*"([^"]+)"', json_str)
                                    if name_match:
                                        t_name = name_match.group(1)

                                        # Жесткий парсинг execute_command (вытаскиваем команду даже с битыми кавычками)
                                        if t_name == "execute_command":
                                            cmd_match = re.search(r'"command"\s*:\s*"(.*)', json_str, re.DOTALL)
                                            if cmd_match:
                                                cmd = cmd_match.group(1)
                                                # Отрезаем закрывающий мусор JSON (например: "} или "}} )
                                                cmd = re.sub(r'"\s*\}?\s*\}?$', '', cmd)
                                                return json_str, {"name": t_name, "arguments": {"command": cmd}}

                                        # Жесткий парсинг для команд с путями (где ломаются слэши Windows)
                                        for single_arg_cmd, arg_key in [("set_working_directory", "new_path"),
                                                                        ("read_file", "path"),
                                                                        ("search_files", "pattern")]:
                                            if t_name == single_arg_cmd:
                                                arg_match = re.search(rf'"{arg_key}"\s*:\s*"(.*)', json_str, re.DOTALL)
                                                if arg_match:
                                                    val = arg_match.group(1)
                                                    val = re.sub(r'"\s*\}?\s*\}?$', '', val)
                                                    return json_str, {"name": t_name, "arguments": {arg_key: val}}
                                    # -----------------------------------

                                # Если этот кусок не подошел, ищем следующую открывающую скобку
                                found_match = True
                                start_idx = text.find('{', i + 1)
                                break

                        if not found_match:
                            break

                    return None

                extracted = extract_tool_json(content_str)

                if extracted:
                    raw_json, fake_tool_call = extracted

                    try:
                        # Обязательно переводим аргументы в строку, как того требует стандарт API
                        args = fake_tool_call.get("arguments", {})
                        if isinstance(args, dict):
                            args = json.dumps(args, ensure_ascii=False)
                        elif isinstance(args, str):
                            # На случай если модель уже вернула аргументы как строку
                            pass

                        # Искусственно создаем правильный вызов инструмента
                        msg_dict["tool_calls"] = [{
                            "id": f"call_fixed_{i}",
                            "type": "function",
                            "function": {
                                "name": fake_tool_call["name"],
                                "arguments": args
                            }
                        }]

                        # ВЫРЕЗАЕМ этот JSON из текста
                        clean_text = content_str.replace(raw_json, "").strip()

                        # Мощная очистка от остаточного мусора (например пустых скобок массива или артефактов)
                        clean_text = re.sub(r'(?i)Tool\s*Calls?:\s*\[\s*\]', '', clean_text).strip()
                        clean_text = re.sub(r'^\[\s*\]$', '', clean_text).strip()
                        clean_text = re.sub(r'```json\s*```|```\s*```', '', clean_text).strip()

                        msg_dict["content"] = clean_text if clean_text else None

                        logger.info(
                            f"Успешно перехвачен текстовый JSON и конвертирован в инструмент: {fake_tool_call['name']}")
                    except Exception as e:
                        logger.error(f"Ошибка обработки перехваченного JSON: {e}")

            messages.append(msg_dict)
            new_messages.append(self._prepare_message_for_db(msg_dict))

            # Если инструментов для вызова нет - прерываем цикл (модель дала окончательный ответ)
            if not msg_dict.get("tool_calls"):
                break

            force_break = False
            for tool_call in msg_dict.get("tool_calls", []):
                name = tool_call["function"]["name"]
                args_str = tool_call["function"]["arguments"]
                try:
                    args = json.loads(args_str)
                except:
                    args = {}

                # Защита от бесконечных циклов (повторение одной и той же команды)
                tool_signature = f"{name}_{args_str}"
                if tool_signature in executed_tools_history:
                    force_break = True
                    break
                executed_tools_history.add(tool_signature)

                if name in self._tool_map:
                    if name == "set_working_directory":
                        result, potential_new_dir = self.tools.set_working_directory(current_dir,
                                                                                     args.get("new_path", "."))
                        if potential_new_dir:
                            current_dir = potential_new_dir
                            new_dir = potential_new_dir
                    else:
                        result = self._tool_map[name](current_dir, **args)
                else:
                    result = f"Ошибка: Инструмент {name} не существует."

                # Сохраняем действие в отчет
                clean_res = str(result).strip()
                executed_actions_report.append({
                    "tool": name,
                    "args": args,
                    "result": clean_res
                })

                # Сообщаем модели результат выполнения функции
                tool_res_msg = {
                    "role": "tool",
                    "tool_call_id": tool_call.get("id", f"call_{i}"),
                    "name": name,
                    "content": f"РЕЗУЛЬТАТ:\n{result}\n\nСИСТЕМНАЯ ИНСТРУКЦИЯ: Ответь пользователю."
                }
                messages.append(tool_res_msg)
                new_messages.append(tool_res_msg)

            if force_break: break

        # ОПРЕДЕЛЕНИЕ ФИНАЛЬНОГО ТЕКСТА
        final_text = ""
        # 1. Ищем последний осмысленный текстовый ответ ассистента
        for msg in reversed(messages):
            # Ищем сообщение с текстом, ТОЛЬКО если в нём НЕТ вызова инструмента (это значит, что это финальный ответ, а не мысли перед действием)
            if msg.get("role") == "assistant" and msg.get("content") and not msg.get("tool_calls"):
                content = str(msg["content"]).strip()
                if content and content != "{}":
                    final_text = content
                    break

        # 2. Если ассистент промолчал в конце (а только вызывал инструменты), формируем системный отчет о том, что он сделал
        if not final_text:
            if executed_actions_report:
                report_parts = ["**Выполнены следующие действия:**"]
                for action in executed_actions_report:
                    args_fmt = ", ".join([f'{k}="{v}"' for k, v in action['args'].items()])
                    report_parts.append(f"— Вызов `{action['tool']}({args_fmt})`")

                    res = action['result']
                    if res and res != "Выполнено (без вывода).":
                        if len(res) > 300: res = res[:300] + "..."
                        report_parts.append(f"  ```text\n  {res}\n  ```")

                if len(report_parts) == 2 and "Вызов" in report_parts[1]:
                    report_parts.append("\n*Операция завершена успешно.*")

                final_text = "\n".join(report_parts)
            else:
                final_text = "Я не смог выполнить запрос. Попробуйте уточнить команду."

        return final_text, new_messages, new_dir