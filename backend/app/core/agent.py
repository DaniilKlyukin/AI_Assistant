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
        }

    def _prepare_message_for_db(self, msg_obj) -> Dict:
        if hasattr(msg_obj, "model_dump"):
            msg_dict = msg_obj.model_dump(exclude_none=True)
        else:
            msg_dict = msg_obj
        allowed_keys = {"role", "content", "tool_calls", "tool_call_id", "name"}
        return {k: v for k, v in msg_dict.items() if k in allowed_keys}

    async def run_cycle(self, user_input: str, history: List[Dict], current_dir: Path,
                        temperature: float = 0.1, top_p: float = 0.9, max_iterations: int = 8) -> Tuple[
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
            1. План действий (Thought): Перед каждым вызовом инструмента обязательно пиши блок <thought>, где объясняешь:
               - Что ты собираешься сделать и зачем.
               - Какие риски существуют (например, при выполнении команд или перезаписи файлов).
            2. Безопасность прежде всего:
               - Перед изменением файла (write_file) ВСЕГДА читай его (read_file), чтобы сохранить важные части кода.
               - Не используй команды удаления (rm, del), если это не было явно запрошено.
            3. Целостность данных: 
               - При записи файла функцией `write_file` ты ДОЛЖЕН передавать ВЕСЬ контент файла целиком. 
               - НИКОГДА не используй заполнители вроде "// остальной код без изменений" или "...". Это сломает файл.
            4. Контекст:
               - Если ты не знаешь, что находится в папке, начни с `get_project_tree` или `list_directory`.
               - Твоя текущая рабочая директория сохраняется между ходами.
            
            ### ФОРМАТ ОТВЕТА:
            1. <thought> Твои размышления </thought>
            2. Вызов функции (через предусмотренный JSON формат инструмента).
            
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
                temperature=temperature,
                top_p=top_p
            )

            resp_obj = response.choices[0].message
            if resp_obj.content and str(resp_obj.content).strip() == "{}":
                resp_obj.content = None

            # Обработка галлюцинаций (если ИИ пишет JSON текстом вместо tool_calls)
            if not resp_obj.tool_calls and resp_obj.content:
                json_match = re.search(r'(\{[\s\S]*?"name"[\s\S]*?"arguments"[\s\S]*?\})', resp_obj.content)
                if json_match:
                    try:
                        raw_json = json_match.group(1)
                        fake_tool_call = json.loads(raw_json)
                        if "name" in fake_tool_call:
                            resp_obj.tool_calls = [{
                                "id": f"call_{i}",
                                "type": "function",
                                "function": {
                                    "name": fake_tool_call.get("name"),
                                    "arguments": json.dumps(fake_tool_call.get("arguments", {}))
                                }
                            }]
                            resp_obj.content = None
                    except:
                        pass

            msg_dict = resp_obj.model_dump(exclude_none=True)
            messages.append(msg_dict)
            new_messages.append(self._prepare_message_for_db(msg_dict))

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

                # Защита от бесконечных циклов
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
            if msg.get("role") == "assistant" and msg.get("content"):
                content = str(msg["content"]).strip()
                if content and content != "{}" and '{"name":' not in content:
                    final_text = content
                    break

        # 2. Если ассистент промолчал, формируем отчет из выполненных действий
        if not final_text:
            if executed_actions_report:
                report_parts = ["**Выполнены следующие действия:**"]
                for action in executed_actions_report:
                    # Красиво форматируем аргументы (например, command="mkdir test")
                    args_fmt = ", ".join([f'{k}="{v}"' for k, v in action['args'].items()])
                    report_parts.append(f"— Вызов `{action['tool']}({args_fmt})`")

                    # Добавляем результат, если он не пустой и не стандартный
                    res = action['result']
                    if res and res != "Выполнено (без вывода).":
                        # Ограничиваем длину вывода в отчете
                        if len(res) > 300: res = res[:300] + "..."
                        report_parts.append(f"  ```text\n  {res}\n  ```")

                # Если все результаты были "без вывода", добавим общую пометку
                if len(report_parts) == 2 and "Вызов" in report_parts[1]:
                    report_parts.append("\n*Операция завершена успешно.*")

                final_text = "\n".join(report_parts)
            else:
                final_text = "Я не смог выполнить запрос. Попробуйте уточнить команду."

        return final_text, new_messages, new_dir