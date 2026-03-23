#!/usr/bin/env python3
"""
Индексатор дисков - создает структурированную информацию о файлах и папках
"""

import os
import sys
import json
import datetime
import platform
from pathlib import Path
from typing import Dict, List, Any, Optional
import hashlib


def get_file_info(filepath: Path) -> Dict[str, Any]:
    """Получить полную информацию о файле/папке"""
    try:
        stat = filepath.stat()
        info = {
            "name": filepath.name,
            "path": str(filepath.absolute()),
            "type": "directory" if filepath.is_dir() else "file",
            "size": stat.st_size if filepath.is_file() else 0,
            "created": datetime.datetime.fromtimestamp(stat.st_ctime).isoformat(),
            "modified": datetime.datetime.fromtimestamp(stat.st_mtime).isoformat(),
            "accessed": datetime.datetime.fromtimestamp(stat.st_atime).isoformat(),
            "permissions": oct(stat.st_mode)[-3:],
            "owner": stat.st_uid if hasattr(stat, 'st_uid') else None,
            "group": stat.st_gid if hasattr(stat, 'st_gid') else None,
        }
        
        # Для файлов добавляем расширение и хеш
        if filepath.is_file():
            info["extension"] = filepath.suffix.lower()
            # Вычисляем хеш только для файлов меньше 10MB
            if stat.st_size < 10 * 1024 * 1024:
                try:
                    with open(filepath, 'rb') as f:
                        file_hash = hashlib.md5(f.read()).hexdigest()
                    info["md5_hash"] = file_hash
                except:
                    info["md5_hash"] = None
            else:
                info["md5_hash"] = "file_too_large"
        else:
            info["extension"] = ""
            info["md5_hash"] = None
            
        return info
    except Exception as e:
        return {
            "name": filepath.name,
            "path": str(filepath.absolute()),
            "type": "error",
            "error": str(e)
        }


def calculate_directory_size(path: Path) -> int:
    """Рекурсивно вычисляет размер директории"""
    total_size = 0
    try:
        for item in path.rglob("*"):
            if item.is_file():
                try:
                    total_size += item.stat().st_size
                except:
                    continue
    except:
        pass
    return total_size


def index_directory(root_path: Path, max_depth: int = 10, 
                    exclude_dirs: List[str] = None) -> Dict[str, Any]:
    """Рекурсивно индексирует директорию"""
    if exclude_dirs is None:
        exclude_dirs = ['.git', '__pycache__', 'node_modules', 'venv', '.idea']
    
    index = {
        "root": str(root_path.absolute()),
        "indexed_at": datetime.datetime.now().isoformat(),
        "system": {
            "platform": platform.platform(),
            "python_version": platform.python_version(),
        },
        "statistics": {
            "total_files": 0,
            "total_dirs": 0,
            "total_size": 0,
            "by_extension": {},
        },
        "structure": {},
    }
    
    def walk_dir(current_path: Path, depth: int, parent_key: str) -> Dict[str, Any]:
        """Рекурсивный обход директории"""
        if depth > max_depth:
            return {}
        
        dir_info = {}
        try:
            items = list(current_path.iterdir())
        except Exception as e:
            return {"error": f"Cannot access directory: {e}"}
        
        for item in items:
            # Пропускаем исключенные директории
            if item.is_dir() and item.name in exclude_dirs:
                continue
                
            item_key = f"{parent_key}/{item.name}" if parent_key else item.name
            info = get_file_info(item)
            
            # Обновляем статистику
            if info["type"] == "file":
                index["statistics"]["total_files"] += 1
                index["statistics"]["total_size"] += info["size"]
                
                ext = info.get("extension", "no_extension")
                index["statistics"]["by_extension"][ext] = \
                    index["statistics"]["by_extension"].get(ext, 0) + 1
            elif info["type"] == "directory":
                index["statistics"]["total_dirs"] += 1
                # Для директорий вычисляем размер
                dir_size = calculate_directory_size(item)
                info["size"] = dir_size
                index["statistics"]["total_size"] += dir_size
                
                # Рекурсивно обходим поддиректорию
                info["contents"] = walk_dir(item, depth + 1, item_key)
            
            dir_info[item.name] = info
        
        return dir_info
    
    index["structure"] = walk_dir(root_path, 0, "")
    return index


def save_index_to_json(index: Dict[str, Any], output_file: str) -> None:
    """Сохраняет индекс в JSON файл"""
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(index, f, indent=2, ensure_ascii=False)
    print(f"Индекс сохранен в: {output_file}")


def save_index_to_text(index: Dict[str, Any], output_file: str) -> None:
    """Сохраняет индекс в читаемом текстовом формате"""
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(f"=" * 80 + "\n")
        f.write(f"ИНДЕКС ДИСКА\n")
        f.write(f"=" * 80 + "\n\n")
        
        f.write(f"Корневая директория: {index['root']}\n")
        f.write(f"Время индексации: {index['indexed_at']}\n")
        f.write(f"Система: {index['system']['platform']}\n\n")
        
        stats = index["statistics"]
        f.write(f"СТАТИСТИКА:\n")
        f.write(f"  Всего файлов: {stats['total_files']:,}\n")
        f.write(f"  Всего папок: {stats['total_dirs']:,}\n")
        f.write(f"  Общий размер: {stats['total_size']:,} байт ({stats['total_size'] / 1024**2:.2f} MB)\n\n")
        
        f.write(f"РАСПРЕДЕЛЕНИЕ ПО РАСШИРЕНИЯМ:\n")
        for ext, count in sorted(stats['by_extension'].items(), key=lambda x: x[1], reverse=True)[:20]:
            f.write(f"  {ext or 'без расширения'}: {count:,}\n")
        f.write("\n")
        
        f.write(f"СТРУКТУРА ФАЙЛОВ:\n")
        f.write(f"-" * 80 + "\n")
        
        def print_structure(contents: Dict[str, Any], indent: int = 0):
            for name, info in sorted(contents.items()):
                prefix = "  " * indent
                if info["type"] == "directory":
                    f.write(f"{prefix}📁 {name}/\n")
                    if "contents" in info:
                        print_structure(info["contents"], indent + 1)
                elif info["type"] == "file":
                    size_str = f"{info['size']:,}b"
                    date_str = datetime.datetime.fromisoformat(info['modified']).strftime('%Y-%m-%d %H:%M')
                    f.write(f"{prefix}📄 {name} ({size_str}, {date_str})\n")
                elif info["type"] == "error":
                    f.write(f"{prefix}❌ {name} - ОШИБКА: {info.get('error', 'unknown')}\n")
        
        print_structure(index["structure"])
    
    print(f"Текстовый отчет сохранен в: {output_file}")


def find_largest_files(index: Dict[str, Any], top_n: int = 20) -> List[Dict[str, Any]]:
    """Находит самые большие файлы в индексе"""
    large_files = []
    
    def collect_files(contents: Dict[str, Any], current_path: str = ""):
        for name, info in contents.items():
            full_path = f"{current_path}/{name}" if current_path else name
            if info["type"] == "file" and "size" in info:
                large_files.append({
                    "path": full_path,
                    "size": info["size"],
                    "modified": info["modified"],
                })
            elif info["type"] == "directory" and "contents" in info:
                collect_files(info["contents"], full_path)
    
    collect_files(index["structure"])
    large_files.sort(key=lambda x: x["size"], reverse=True)
    return large_files[:top_n]


def main():
    """Основная функция"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Индексация файловой системы')
    parser.add_argument('path', nargs='?', default='.', 
                       help='Путь для индексации (по умолчанию текущая директория)')
    parser.add_argument('--depth', type=int, default=10,
                       help='Максимальная глубина рекурсии (по умолчанию 10)')
    parser.add_argument('--json', type=str, default='disk_index.json',
                       help='Имя JSON файла для сохранения (по умолчанию disk_index.json)')
    parser.add_argument('--txt', type=str, default='disk_index.txt',
                       help='Имя текстового файла для сохранения (по умолчанию disk_index.txt)')
    parser.add_argument('--exclude', nargs='+', default=['.git', '__pycache__'],
                       help='Директории для исключения')
    parser.add_argument('--show-largest', type=int, default=0,
                       help='Показать N самых больших файлов')
    
    args = parser.parse_args()
    
    target_path = Path(args.path).absolute()
    
    if not target_path.exists():
        print(f"Ошибка: путь '{target_path}' не существует")
        sys.exit(1)
    
    print(f"Начинаю индексацию: {target_path}")
    print(f"Глубина рекурсии: {args.depth}")
    print(f"Исключаемые директории: {', '.join(args.exclude)}")
    print("-" * 60)
    
    # Индексация
    index = index_directory(target_path, max_depth=args.depth, exclude_dirs=args.exclude)
    
    # Сохранение результатов
    save_index_to_json(index, args.json)
    save_index_to_text(index, args.txt)
    
    # Вывод статистики
    stats = index["statistics"]
    print(f"\nИНДЕКСАЦИЯ ЗАВЕРШЕНА!")
    print(f"Обработано файлов: {stats['total_files']:,}")
    print(f"Обработано папок: {stats['total_dirs']:,}")
    print(f"Общий размер: {stats['total_size'] / 1024**3:.2f} GB")
    
    # Показ самых больших файлов
    if args.show_largest > 0:
        print(f"\nТОП-{args.show_largest} САМЫХ БОЛЬШИХ ФАЙЛОВ:")
        largest = find_largest_files(index, args.show_largest)
        for i, file_info in enumerate(largest, 1):
            size_mb = file_info["size"] / 1024**2
            print(f"{i:2d}. {file_info['path']} ({size_mb:.1f} MB)")
    
    print(f"\nРезультаты сохранены в:\n  {args.json} (JSON)\n  {args.txt} (текстовый отчет)")


if __name__ == "__main__":
    main()