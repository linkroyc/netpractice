"""Модуль 3. Диагностика."""

QUESTIONS = [
    {
        "id": "m3-01",
        "module": 3,
        "topic": "ipconfig",
        "difficulty": 1,
        "type": "choice",
        "prompt": "Какая команда Windows покажет IP-адрес, маску подсети и шлюз по умолчанию?",
        "options": ["ping", "ipconfig", "netstat", "tracert"],
        "correct": 1,
        "explanation": (
            "ipconfig без параметров выводит основные параметры активных адаптеров: "
            "IP-адрес, маску и шлюз. Для полной информации используют ipconfig /all."
        ),
        "sample": "ipconfig",
    },
    {
        "id": "m3-02",
        "module": 3,
        "topic": "ipconfig",
        "difficulty": 1,
        "type": "input",
        "prompt": (
            "Какой командой Windows посмотреть полную информацию об адаптерах: "
            "MAC-адрес, DHCP-сервер и DNS-серверы?"
        ),
        "answer_kind": "text",
        "answers": ["ipconfig /all", "ipconfig/all"],
        "explanation": (
            "ipconfig /all показывает не только IP, маску и шлюз, но и физический "
            "адрес (MAC), сведения о DHCP, DNS-серверы и срок аренды."
        ),
        "sample": "ipconfig /all",
    },
    {
        "id": "m3-03",
        "module": 3,
        "topic": "ping",
        "difficulty": 1,
        "type": "choice",
        "prompt": "Что проверяет команда ping?",
        "options": [
            "Доступность узла по протоколу ICMP",
            "Правильность DNS-записей",
            "Открытые TCP-порты",
            "Содержимое таблицы ARP",
        ],
        "correct": 0,
        "explanation": (
            "ping отправляет ICMP echo-запрос и ждёт ответ. Он проверяет "
            "доступность узла и время отклика, но не показывает открытые порты "
            "и не заменяет проверку DNS."
        ),
        "sample": "ping проверяет доступность через ICMP.",
    },
    {
        "id": "m3-04",
        "module": 3,
        "topic": "tracert",
        "difficulty": 1,
        "type": "input",
        "prompt": "Какой командой в Windows посмотреть маршрут до узла?",
        "answer_kind": "text",
        "answers": ["tracert", "tracert 8.8.8.8"],
        "explanation": (
            "tracert показывает последовательность маршрутизаторов до цели. "
            "В Linux аналогичная команда называется traceroute."
        ),
        "sample": "tracert 8.8.8.8",
    },
    {
        "id": "m3-05",
        "module": 3,
        "topic": "traceroute",
        "difficulty": 1,
        "type": "input",
        "prompt": "Как называется команда трассировки маршрута в Linux?",
        "answer_kind": "text",
        "answers": ["traceroute", "traceroute 8.8.8.8"],
        "explanation": (
            "В Linux используется traceroute. В Windows аналогичная команда — "
            "tracert."
        ),
        "sample": "traceroute 8.8.8.8",
    },
    {
        "id": "m3-06",
        "module": 3,
        "topic": "nslookup",
        "difficulty": 1,
        "type": "choice",
        "prompt": "Для чего используется команда nslookup?",
        "options": [
            "Для проверки ответа DNS-сервера по имени или адресу",
            "Для просмотра таблицы маршрутизации",
            "Для настройки VLAN",
            "Для проверки скорости канала",
        ],
        "correct": 0,
        "explanation": (
            "nslookup запрашивает у DNS-сервера запись для имени или, наоборот, "
            "имя для IP-адреса. Это основной простой инструмент проверки DNS."
        ),
        "sample": "nslookup example.com",
    },
    {
        "id": "m3-07",
        "module": 3,
        "topic": "ARP",
        "difficulty": 1,
        "type": "input",
        "prompt": "Какой командой Windows посмотреть таблицу ARP?",
        "answer_kind": "text",
        "answers": ["arp -a", "arp -a 192.168.1.1", "arp /a"],
        "explanation": (
            "arp -a выводит известные соответствия IP-адресов и MAC-адресов. "
            "Таблица помогает проверить, видит ли компьютер соседнее устройство."
        ),
        "sample": "arp -a",
    },
    {
        "id": "m3-08",
        "module": 3,
        "topic": "Диагностика шлюза",
        "difficulty": 2,
        "type": "scenario",
        "prompt": (
            "Компьютер пингует свой шлюз, но не пингует 8.8.8.8. Назовите первые "
            "проверки и объясните, что каждая из них покажет."
        ),
        "keywords": [
            {"label": "Проверить IP-адрес, маску и адрес шлюза", "patterns": ["ipconfig", "маск", "шлюз", "ip-адрес", "ip адрес"]},
            {"label": "Проверить таблицу маршрутов (route print / ip route)", "patterns": ["route print", "ip route", "маршрут"]},
            {"label": "Выполнить tracert, чтобы найти точку обрыва", "patterns": ["tracert", "traceroute", "трассиров"]},
            {"label": "Проверить NAT и подключение провайдера на маршрутизаторе", "patterns": ["nat", "провайдер", "wan", "интернет"]},
            {"label": "Проверить firewall и правила фильтрации", "patterns": ["firewall", "фаервол", "брандмауэр", "файрвол"]},
        ],
        "min_points": 3,
        "explanation": (
            "Доступный шлюз означает, что локальная сеть работает. Дальше важно "
            "убедиться, что в таблице есть маршрут по умолчанию через этот шлюз, "
            "что маршрутизатор имеет подключение к провайдеру и выполняет NAT, "
            "а firewall не блокирует трафик. tracert покажет, на каком шаге путь "
            "обрывается."
        ),
        "sample": (
            "Проверю ipconfig: адрес, маску и шлюз. Затем route print — есть ли "
            "маршрут по умолчанию. Сделаю tracert 8.8.8.8, чтобы увидеть, где "
            "теряется путь. На маршрутизаторе проверю WAN, NAT и firewall."
        ),
    },
    {
        "id": "m3-09",
        "module": 3,
        "topic": "Диагностика DNS",
        "difficulty": 3,
        "type": "troubleshoot",
        "prompt": (
            "У одного компьютера не открывается внутренний сайт по имени, хотя "
            "по IP он открывается. У соседнего компьютера имя работает. Что "
            "проверить?"
        ),
        "keywords": [
            {"label": "Проверить DNS-серверы в ipconfig /all", "patterns": ["dns", "ipconfig all", "ipconfig /all"]},
            {"label": "Сравнить настройки с работающим компьютером", "patterns": ["сравн", "сосед", "работающ", "друг"]},
            {"label": "Выполнить nslookup и проверить ответ", "patterns": ["nslookup", "dig "]},
            {"label": "Проверить DNS-суффикс или запись в DNS", "patterns": ["суффикс", "запис", "зон"]},
            {"label": "Проверить кэш DNS и при необходимости сбросить", "patterns": ["кэш", "flushdns", "очист"]},
        ],
        "min_points": 3,
        "explanation": (
            "Если по IP сайт доступен, сеть и служба работают. Различие между "
            "компьютерами почти наверняка в настройках DNS или в кэше. Сравните "
            "DNS-серверы, проверьте nslookup, DNS-суффикс и запись на DNS-сервере."
        ),
        "sample": (
            "Сравню ipconfig /all с работающим ПК, проверю адреса DNS. Выполню "
            "nslookup имени и посмотрю, какой сервер отвечает. Проверю DNS-суффикс, "
            "запись в зоне и при необходимости сброшу кэш ipconfig /flushdns."
        ),
    },
    {
        "id": "m3-10",
        "module": 3,
        "topic": "Linux: сетевые адреса",
        "difficulty": 1,
        "type": "input",
        "prompt": "Какой командой Linux посмотреть IP-адреса сетевых интерфейсов?",
        "answer_kind": "text",
        "answers": ["ip addr", "ip a", "ip address", "ifconfig"],
        "explanation": (
            "Современная команда — ip addr (сокращённо ip a). Старая команда "
            "ifconfig тоже встречается, но в новых системах может требовать "
            "установки пакета net-tools."
        ),
        "sample": "ip addr",
    },
    {
        "id": "m3-11",
        "module": 3,
        "topic": "Диагностика доступности",
        "difficulty": 3,
        "type": "scenario",
        "prompt": (
            "При ping 192.168.1.50 компьютер отвечает «Destination host "
            "unreachable». Какие действия вы выполните по порядку?"
        ),
        "keywords": [
            {"label": "Проверить свой IP, маску и шлюз", "patterns": ["ipconfig", "ip addr", "маск", "шлюз"]},
            {"label": "Проверить кабель, Wi-Fi или порт коммутатора", "patterns": ["кабел", "wi-fi", "wifi", "порт", "коммутатор"]},
            {"label": "Посмотреть таблицу ARP (arp -a) и наличие соседа", "patterns": ["arp"]},
            {"label": "Проверить, в той ли подсети находится адрес назначения", "patterns": ["подсет", "маск", "диапазон"]},
            {"label": "Проверить VLAN и firewall на пути", "patterns": ["vlan", "firewall", "брандмауэр", "фаервол"]},
        ],
        "min_points": 3,
        "explanation": (
            "«Destination host unreachable» часто означает, что узел не удалось "
            "найти на канальном уровне или нет маршрута. Начинают с собственных "
            "параметров и физического подключения, затем проверяют ARP, подсеть "
            "адресата и VLAN/firewall."
        ),
        "sample": (
            "Проверю ipconfig: свой адрес, маску и шлюз. Убедюсь, что кабель или "
            "Wi-Fi работают. Посмотрю arp -a, есть ли MAC адресата. Проверю, в "
            "одной ли подсети мы находимся, затем VLAN и firewall."
        ),
    },
    {
        "id": "m3-12",
        "module": 3,
        "topic": "ipconfig /all",
        "difficulty": 1,
        "type": "choice",
        "prompt": "Что означает строка «Физический адрес» в выводе ipconfig /all?",
        "options": [
            "IP-адрес адаптера",
            "MAC-адрес сетевого адаптера",
            "Адрес шлюза по умолчанию",
            "Адрес DNS-сервера",
        ],
        "correct": 1,
        "explanation": (
            "«Физический адрес» — это MAC-адрес адаптера, например "
            "00-1A-2B-3C-4D-5E. Его можно использовать для поиска устройства "
            "в таблице коммутатора."
        ),
        "sample": "Физический адрес = MAC-адрес.",
    },
]
