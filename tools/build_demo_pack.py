"""Собрать демонстрационный пакет demo_packs/ipv4-basics.nptpack.

Запуск из корня проекта:
    python tools/build_demo_pack.py
"""

from __future__ import annotations

import hashlib
import struct
import sys
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from packs import build_zip, parse_pack_bytes  # noqa: E402

MANIFEST = {
    "format": "nptpack",
    "format_version": 1,
    "id": "ipv4-basics",
    "title": "Основы IPv4 и подсетей",
    "description": (
        "Практический курс по IPv4: структура адреса, маски, CIDR, "
        "частные и публичные сети, адрес сети, broadcast и расчёт подсетей."
    ),
    "author": "NetPractice Community",
    "module_version": "1.0.0",
    "language": "ru",
    "difficulty": "beginner",
    "category": "networking",
    "created_at": "2026-10-31",
    "min_app_version": "1.0.0",
}


def make_png(width: int, height: int, nodes, lines, filename: str) -> dict:
    """Нарисовать простую схему без внешних библиотек (RGB PNG)."""
    pixels = [[(15, 23, 32) for _ in range(width)] for _ in range(height)]

    def rect(x, y, w, h, color):
        for py in range(max(0, y), min(height, y + h)):
            for px in range(max(0, x), min(width, x + w)):
                pixels[py][px] = color

    def line(x1, y1, x2, y2, color):
        steps = max(abs(x2 - x1), abs(y2 - y1), 1)
        for step in range(steps + 1):
            x = round(x1 + (x2 - x1) * step / steps)
            y = round(y1 + (y2 - y1) * step / steps)
            rect(x - 1, y - 1, 3, 3, color)

    for x1, y1, x2, y2, color in lines:
        line(x1, y1, x2, y2, color)
    for x, y, color in nodes:
        rect(x, y, 92, 52, color)
        rect(x + 8, y + 10, 76, 5, (233, 240, 247))
        rect(x + 8, y + 22, 48, 5, (159, 176, 193))

    raw = b"".join(
        b"\x00" + b"".join(bytes(pixel) for pixel in row) for row in pixels
    )

    def chunk(tag, data):
        return (
            struct.pack(">I", len(data)) + tag + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )
    return {
        "data": png,
        "media_type": "image/png",
        "size": len(png),
        "width": width,
        "height": height,
        "sha256": hashlib.sha256(png).hexdigest(),
        "filename": filename,
    }


QUESTIONS = [
    {
        "id": "q01", "topic": "Структура IPv4", "type": "input",
        "prompt": "Сколько октетов содержит IPv4-адрес?",
        "difficulty": 1, "xp": 10, "answer_kind": "int", "answers": ["4"],
        "explanation": "IPv4-адрес состоит из четырёх 8-битных октетов.",
        "sample": "192.168.10.1 — четыре октета: 192, 168, 10, 1.",
        "hints": ["Посчитайте группы цифр, разделённые точками."],
    },
    {
        "id": "q02", "topic": "Маска подсети", "type": "input",
        "prompt": "Запишите маску для префикса /26 в точечной нотации.",
        "difficulty": 1, "xp": 12, "answer_kind": "mask",
        "answers": ["255.255.255.192", "/26"],
        "explanation": "26 бит — это 24 бита сети и 2 бита подсети: 255.255.255.192.",
        "sample": "24 единицы + 2 единицы = 255.255.255.192.",
        "hints": ["Первые 24 бита дают 255.255.255, остаток — 192."],
    },
    {
        "id": "q03", "topic": "CIDR", "type": "input",
        "prompt": "Сколько единичных бит в маске /27?",
        "difficulty": 1, "xp": 10, "answer_kind": "int", "answers": ["27"],
        "explanation": "Число после слэша в CIDR — количество единичных бит маски.",
        "sample": "/27 = 27 единиц и 5 нулей.",
        "hints": ["CIDR — это просто длина префикса."],
    },
    {
        "id": "q04", "topic": "Количество узлов", "type": "input",
        "prompt": "Сколько используемых адресов узлов в подсети /27?",
        "difficulty": 2, "xp": 12, "answer_kind": "int", "answers": ["30"],
        "explanation": "В /27 32 адреса, два из них сеть и broadcast: 30 узлов.",
        "sample": "2^(32−27) − 2 = 32 − 2 = 30.",
        "hints": ["Вычтите адрес сети и широковещательный адрес."],
    },
    {
        "id": "q05", "topic": "Расчёт подсети", "type": "multi",
        "prompt": "Для 192.168.1.130/26 определите адрес сети, broadcast и число узлов.",
        "difficulty": 2, "xp": 15,
        "fields": [
            {"key": "network", "label": "Адрес сети", "kind": "ip", "answers": ["192.168.1.128"]},
            {"key": "broadcast", "label": "Broadcast", "kind": "ip", "answers": ["192.168.1.191"]},
            {"key": "hosts", "label": "Узлов", "kind": "int", "answers": ["62"]},
        ],
        "explanation": "Блок /26 — 64 адреса. Для .130 это диапазон .128–.191, узлов 62.",
        "sample": "Сеть 192.168.1.128, broadcast 192.168.1.191, 62 хоста.",
        "hints": ["/26 — это шаг 64."],
    },
    {
        "id": "q06", "topic": "Частные адреса", "type": "choice",
        "prompt": "Какой адрес относится к частным сетям?",
        "difficulty": 1, "xp": 10,
        "options": ["8.8.8.8", "172.16.10.5", "1.1.1.1", "203.0.113.20"],
        "correct": 1,
        "explanation": "172.16.0.0/12 входит в частные диапазоны RFC 1918.",
        "sample": "Частные: 10/8, 172.16/12, 192.168/16.",
        "hints": ["Вспомните три диапазона RFC 1918."],
    },
    {
        "id": "q07", "topic": "Маска и CIDR", "type": "choice",
        "prompt": "Какому префиксу соответствует маска 255.255.255.224?",
        "difficulty": 1, "xp": 10,
        "options": ["/25", "/26", "/27", "/28"], "correct": 2,
        "explanation": "224 — это 11100000, три единицы после /24, итого /27.",
        "sample": "255.255.255.224 = /27.",
        "hints": ["224 = 128 + 64 + 32."],
    },
    {
        "id": "q08", "topic": "Адрес сети", "type": "input",
        "prompt": "Укажите адрес сети для 10.20.30.40/22.",
        "difficulty": 2, "xp": 12, "answer_kind": "ip", "answers": ["10.20.28.0"],
        "explanation": "/22 — шаг 4 в третьем октете. 30 попадает в блок 28–31.",
        "sample": "10.20.28.0/22.",
        "hints": ["Третий октет меняется блоками по 4."],
    },
    {
        "id": "q09", "topic": "Broadcast", "type": "input",
        "prompt": "Укажите широковещательный адрес для 10.20.30.40/22.",
        "difficulty": 2, "xp": 12, "answer_kind": "ip", "answers": ["10.20.31.255"],
        "explanation": "Блок 10.20.28.0/22 заканчивается на 10.20.31.255.",
        "sample": "Последний адрес блока 28–31 — .31.255.",
        "hints": ["Сначала найдите адрес сети."],
    },
    {
        "id": "q10", "topic": "Диапазон узлов", "type": "input",
        "prompt": "Какой первый используемый адрес узла в 172.16.5.0/24?",
        "difficulty": 1, "xp": 12, "answer_kind": "ip", "answers": ["172.16.5.1"],
        "explanation": "Адрес сети .0, первый узел — .1.",
        "sample": "172.16.5.1.",
        "hints": ["Первый адрес после адреса сети."],
    },
    {
        "id": "q11", "topic": "Деление на подсети", "type": "multi",
        "prompt": "Сеть 192.168.0.0/24 делят на 4 равные подсети. Укажите маску, число подсетей и число узлов в каждой.",
        "difficulty": 2, "xp": 15,
        "fields": [
            {"key": "mask", "label": "Маска", "kind": "mask", "answers": ["255.255.255.192", "/26"]},
            {"key": "subnets", "label": "Подсетей", "kind": "int", "answers": ["4"]},
            {"key": "hosts", "label": "Узлов в подсети", "kind": "int", "answers": ["62"]},
        ],
        "explanation": "Для 4 подсетей нужно 2 бита: /26, по 64 адреса и 62 узла.",
        "sample": "/26; 4 подсети; 62 узла.",
        "hints": ["2 бита дают 4 комбинации."],
    },
    {
        "id": "q12", "topic": "Публичные адреса", "type": "choice",
        "prompt": "Какой адрес является публичным?",
        "difficulty": 1, "xp": 10,
        "options": ["192.168.10.20", "10.0.0.5", "172.31.255.254", "203.0.113.10"],
        "correct": 3,
        "explanation": "203.0.113.10 не входит в диапазоны RFC 1918.",
        "sample": "203.0.113.10 — публичный адрес.",
        "hints": ["Проверьте 10/8, 172.16/12 и 192.168/16."],
    },
    {
        "id": "q13", "topic": "Диагностика адресации", "type": "scenario",
        "prompt": "Почему компьютер 192.168.1.100/24 не пингует 192.168.2.100 без маршрутизатора?",
        "difficulty": 2, "xp": 20,
        "keywords": [
            {"label": "Разные подсети", "patterns": ["разные подсет", "другой подсет", "разных сет"]},
            {"label": "Нужен маршрутизатор или шлюз", "patterns": ["маршрутизатор", "шлюз", "router"]},
            {"label": "Маска /24", "patterns": ["/24", "255.255.255.0", "маск"]},
        ],
        "min_points": 2,
        "explanation": "192.168.1.0/24 и 192.168.2.0/24 — разные сети; связь между ними обеспечивает маршрутизатор.",
        "sample": "Адреса в разных подсетях, поэтому нужен шлюз по умолчанию и маршрутизация.",
        "hints": ["Сравните адреса сети, а не только первые три октета."],
    },
    {
        "id": "q14", "topic": "Поиск неисправности", "type": "troubleshoot",
        "prompt": "Компьютер 192.168.1.50/26 не видит 192.168.1.70. Что проверить в первую очередь?",
        "difficulty": 3, "xp": 25,
        "keywords": [
            {"label": "Проверить маску /26", "patterns": ["/26", "255.255.255.192", "маск"]},
            {"label": "Адрес сети .64", "patterns": ["192.168.1.64", "адрес сети", "подсет"]},
            {"label": "Шлюз и ping", "patterns": ["шлюз", "gateway", "ping", "ipconfig"]},
        ],
        "min_points": 2,
        "explanation": "В /26 адреса .0–.63 и .64–.127 — разные подсети; проверьте маску, адрес сети и шлюз.",
        "sample": "ipconfig /all, сравнить маску и адрес сети, затем ping шлюза.",
        "hints": ["Разбейте /24 на четыре блока по 64 адреса."],
    },
    {
        "id": "q15", "topic": "Broadcast /24", "type": "choice",
        "prompt": "Какой broadcast у сети 172.16.10.0/24?",
        "difficulty": 1, "xp": 10,
        "options": ["172.16.10.0", "172.16.10.1", "172.16.10.254", "172.16.10.255"],
        "correct": 3,
        "explanation": "Последний адрес /24 — 172.16.10.255.",
        "sample": "172.16.10.255.",
        "hints": ["Это последний адрес блока из 256 адресов."],
    },
]


LABS = [
    {
        "id": "lab-subnets",
        "title": "Разбиение сети /24 на четыре подсети",
        "description": "Рассчитайте четыре подсети и проверьте адресацию на практике.",
        "goal": "Научиться делить /24 на равные подсети и назначать корректные адреса.",
        "prerequisites": [
            "Компьютер с Windows/Linux и доступом к настройкам сети.",
            "Знание десятичной записи IPv4 и префикса CIDR.",
        ],
        "theory": "Для четырёх подсетей из /24 нужно занять два бита: получится /26. Каждая подсеть содержит 64 адреса, из них 62 доступны узлам.",
        "steps": [
            "Запишите исходную сеть 192.168.50.0/24.",
            "Определите новый префикс /26 и маску 255.255.255.192.",
            "Выпишите адреса сетей: .0, .64, .128, .192.",
            "Для каждой подсети укажите broadcast и диапазон узлов.",
            "Назначьте компьютеру адрес из одной подсети и проверьте связь с адресом из другой.",
        ],
        "commands": [
            "ipconfig /all",
            "ping 192.168.50.70",
            "ip addr show",
        ],
        "expected": [
            "Четыре подсети: 192.168.50.0/26, .64/26, .128/26, .192/26.",
            "В каждой подсети 62 доступных адреса узлов.",
            "Адреса из разных подсетей не пингуются напрямую без маршрутизатора.",
        ],
        "criteria": [
            "Верно указана маска /26.",
            "Все четыре адреса сетей рассчитаны без пересечений.",
            "Для каждой подсети указан корректный broadcast.",
        ],
        "hints": [
            "Шаг /26 равен 64.",
            "Адрес сети кратен размеру блока.",
        ],
        "explanation": "Деление /24 на 4 подсети — это сдвиг префикса на 2 бита. Проверка через ping показывает, что без маршрутизатора разные подсети изолированы.",
        "manual_check": True,
        "assets": ["assets/subnetting-example.png"],
    },
    {
        "id": "lab-diagnose",
        "title": "Диагностика связи между двумя подсетями",
        "description": "Соберите факты о сети и объясните, почему адреса не видят друг друга.",
        "goal": "Научиться отличать проблему маски от проблемы маршрутизации.",
        "prerequisites": [
            "Два устройства или две виртуальные машины в одной физической сети.",
            "Доступ к командной строке.",
        ],
        "theory": "Адрес 192.168.60.50/26 находится в подсети 192.168.60.0/26, а 192.168.60.70/26 — в 192.168.60.64/26. Это разные подсети.",
        "steps": [
            "Проверьте IP-адрес, маску и шлюз на обоих устройствах.",
            "Определите адрес сети для каждого адреса.",
            "Выполните ping между устройствами.",
            "Проверьте ARP-таблицу и доступность шлюза.",
            "Сформулируйте, чего не хватает для связи.",
        ],
        "commands": [
            "ipconfig /all",
            "arp -a",
            "ping 192.168.60.70",
            "tracert 192.168.60.70",
        ],
        "expected": [
            "Адреса находятся в разных подсетях /26.",
            "Прямой ping не проходит без маршрутизатора.",
            "Шлюз доступен, если настроен корректно.",
        ],
        "criteria": [
            "Указаны обе подсети и их границы.",
            "Объяснена роль шлюза по умолчанию.",
            "Приведены конкретные команды проверки.",
        ],
        "hints": [
            "Сравните адреса сетей, а не только IP.",
            "ARP показывает соседей только в локальной подсети.",
        ],
        "explanation": "Маска /26 делит /24 на четыре блока. Устройства в разных блоках не общаются напрямую; нужен маршрутизатор и корректные шлюзы.",
        "manual_check": True,
        "assets": ["assets/topology-example.png"],
    },
]


def main():
    assets = {
        "assets/subnetting-example.png": make_png(
            640, 280,
            [(60, 110, (87, 201, 165)), (274, 110, (121, 174, 247)), (488, 110, (242, 198, 109))],
            [
                (152, 136, 274, 136, (159, 176, 193)),
                (366, 136, 488, 136, (159, 176, 193)),
            ],
            "assets/subnetting-example.png",
        ),
        "assets/topology-example.png": make_png(
            640, 280,
            [(60, 60, (121, 174, 247)), (60, 180, (242, 198, 109)), (488, 120, (87, 201, 165))],
            [
                (152, 86, 488, 146, (159, 176, 193)),
                (152, 206, 488, 146, (159, 176, 193)),
            ],
            "assets/topology-example.png",
        ),
    }
    raw = build_zip(MANIFEST, QUESTIONS, LABS, assets)
    parse_pack_bytes(raw)  # тот же валидатор, что и при импорте
    destination = ROOT / "demo_packs" / "ipv4-basics.nptpack"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(raw)
    print(f"written: {destination} ({len(raw)} bytes, {len(QUESTIONS)} questions, {len(LABS)} labs)")


if __name__ == "__main__":
    main()
