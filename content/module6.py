"""Модуль 6. Основы Linux и серверов."""

QUESTIONS = [
    {
        "id": "m6-01",
        "module": 6,
        "topic": "Файлы и каталоги",
        "difficulty": 1,
        "type": "input",
        "prompt": (
            "Какой командой Linux посмотреть содержимое каталога с подробной "
            "информацией, включая права доступа?"
        ),
        "answer_kind": "text",
        "answers": ["ls -l", "ls -la", "ls -al", "ls -lh", "ls -lha"],
        "explanation": (
            "ls выводит содержимое каталога, а ключ -l включает подробный формат: "
            "права, владельца, группу, размер и дату. Ключ -a дополнительно "
            "показывает скрытые файлы."
        ),
        "sample": "ls -l",
    },
    {
        "id": "m6-02",
        "module": 6,
        "topic": "Навигация",
        "difficulty": 1,
        "type": "choice",
        "prompt": "Какая команда меняет текущий каталог в Linux?",
        "options": ["cd", "ls", "pwd", "cp"],
        "correct": 0,
        "explanation": (
            "cd (change directory) переходит в другой каталог. pwd показывает "
            "текущий путь, ls — содержимое, cp — копирует файлы."
        ),
        "sample": "cd /var/log",
    },
    {
        "id": "m6-03",
        "module": 6,
        "topic": "Права доступа",
        "difficulty": 2,
        "type": "input",
        "prompt": (
            "Какую числовую запись прав нужно задать файлу, чтобы владелец мог "
            "читать, записывать и выполнять, а группа и остальные — только "
            "читать и выполнять? Укажите три цифры."
        ),
        "answer_kind": "int",
        "answers": ["755"],
        "explanation": (
            "Чтение = 4, запись = 2, выполнение = 1. Владелец: 4+2+1 = 7. "
            "Группа: 4+1 = 5. Остальные: 4+1 = 5. Итого 755 (rwxr-xr-x)."
        ),
        "sample": "chmod 755 файл",
    },
    {
        "id": "m6-04",
        "module": 6,
        "topic": "Сеть в Linux",
        "difficulty": 1,
        "type": "input",
        "prompt": "Какой командой Linux посмотреть IP-адреса и состояние интерфейсов?",
        "answer_kind": "text",
        "answers": ["ip addr", "ip a", "ip address", "ifconfig"],
        "explanation": (
            "ip addr (или сокращённо ip a) показывает интерфейсы, их адреса и "
            "состояние. Команда ifconfig — устаревший аналог."
        ),
        "sample": "ip addr",
    },
    {
        "id": "m6-05",
        "module": 6,
        "topic": "Службы",
        "difficulty": 2,
        "type": "input",
        "prompt": "Какой командой проверить состояние службы SSH в systemd?",
        "answer_kind": "text",
        "answers": ["systemctl status ssh", "systemctl status sshd", "systemctl status ssh.service", "systemctl status sshd.service"],
        "explanation": (
            "systemctl status показывает, запущена ли служба, её последние "
            "сообщения и код выхода. В Debian/Ubuntu служба обычно называется "
            "ssh, в RHEL-подобных системах — sshd."
        ),
        "sample": "systemctl status ssh",
    },
    {
        "id": "m6-06",
        "module": 6,
        "topic": "Логи",
        "difficulty": 1,
        "type": "input",
        "prompt": "В каком каталоге Linux обычно находятся системные журналы и логи?",
        "answer_kind": "text",
        "answers": ["/var/log", "var/log"],
        "explanation": (
            "Основные файлы журналов лежат в /var/log. Там находятся, например, "
            "syslog, auth.log и каталоги веб-серверов."
        ),
        "sample": "/var/log",
    },
    {
        "id": "m6-07",
        "module": 6,
        "topic": "SSH",
        "difficulty": 3,
        "type": "scenario",
        "prompt": (
            "SSH-подключение к Linux-серверу не устанавливается. Сервер отвечает "
            "на ping. Какие проверки вы выполните?"
        ),
        "keywords": [
            {"label": "Проверить, запущена ли служба SSH", "patterns": ["systemctl", "служб", "ssh", "sshd", "запущен"]},
            {"label": "Проверить, слушается ли порт 22", "patterns": ["порт 22", "22", "ss -", "netstat", "прослуш"]},
            {"label": "Проверить firewall и правила доступа", "patterns": ["firewall", "ufw", "iptables", "firewalld", "брандмауэр"]},
            {"label": "Посмотреть журнал/логи SSH", "patterns": ["journalctl", "лог", "log", "auth.log"]},
            {"label": "Проверить ключи, пароль и настройки sshd_config", "patterns": ["ключ", "парол", "sshd_config", "конфиг"]},
        ],
        "min_points": 3,
        "explanation": (
            "Ping подтверждает только доступность хоста. Далее проверяют службу "
            "SSH, прослушивание порта 22, firewall, журнал (там бывает причина "
            "отказа) и настройки аутентификации. Ошибка клиента тоже возможна, "
            "поэтому полезно посмотреть вывод ssh -v."
        ),
        "sample": (
            "Проверю systemctl status ssh: запущена ли служба. Посмотрю ss -tulpn "
            "— слушается ли 22 порт. Проверю ufw/firewalld. Затем журнал "
            "journalctl -u ssh и настройки sshd_config, а также ключи и пароль."
        ),
    },
    {
        "id": "m6-08",
        "module": 6,
        "topic": "Журналы systemd",
        "difficulty": 2,
        "type": "choice",
        "prompt": "Что показывает команда journalctl -u nginx?",
        "options": [
            "Журнал службы nginx",
            "Список файлов nginx",
            "Открытые порты nginx",
            "Права на конфигурацию nginx",
        ],
        "correct": 0,
        "explanation": (
            "Ключ -u выбирает unit (службу). journalctl -u nginx выводит записи "
            "журнала, связанные с nginx, — удобно при поиске причины ошибки."
        ),
        "sample": "Журнал службы nginx.",
    },
    {
        "id": "m6-09",
        "module": 6,
        "topic": "Чтение логов",
        "difficulty": 1,
        "type": "choice",
        "prompt": "Какая команда покажет последние строки файла журнала?",
        "options": ["head", "tail", "grep", "chmod"],
        "correct": 1,
        "explanation": (
            "tail выводит конец файла, что удобно для свежих записей журнала. "
            "head показывает начало, grep ищет строки, chmod меняет права."
        ),
        "sample": "tail -n 50 /var/log/syslog",
    },
    {
        "id": "m6-10",
        "module": 6,
        "topic": "Диагностика сервера",
        "difficulty": 3,
        "type": "scenario",
        "prompt": (
            "Сервер пингуется, но сайт на нём не открывается. Что проверить на "
            "сервере и с клиента?"
        ),
        "keywords": [
            {"label": "Проверить, запущена ли служба веб-сервера", "patterns": ["systemctl", "служб", "nginx", "apache", "httpd", "запущен"]},
            {"label": "Проверить прослушивание портов 80/443", "patterns": ["80", "443", "ss -", "netstat", "порт"]},
            {"label": "Проверить firewall", "patterns": ["firewall", "ufw", "iptables", "firewalld", "брандмауэр"]},
            {"label": "Посмотреть логи веб-сервера и приложения", "patterns": ["лог", "log", "journalctl", "error"]},
            {"label": "Проверить DNS и доступность с клиента (curl/browser)", "patterns": ["dns", "curl", "nslookup", "браузер", "клиент"]},
        ],
        "min_points": 3,
        "explanation": (
            "Ping проверяет только сетевой уровень. Сайт зависит от службы, "
            "портов, firewall, конфигурации и приложения. С сервера проверяют "
            "systemctl status и ss -tulpn, логи; с клиента — DNS, curl и "
            "доступность порта."
        ),
        "sample": (
            "На сервере проверю systemctl status nginx, ss -tulpn (80/443) и "
            "firewall. Посмотрю логи nginx и приложения. С клиента проверю DNS, "
            "nslookup и curl -I, чтобы понять, на каком шаге обрыв."
        ),
    },
    {
        "id": "m6-11",
        "module": 6,
        "topic": "Права доступа",
        "difficulty": 2,
        "type": "choice",
        "prompt": "Что означает запись прав 644 для файла?",
        "options": [
            "Владелец может читать и писать, группа и остальные — только читать",
            "Все могут читать, писать и выполнять файл",
            "Владелец может только читать, остальные — писать",
            "Файл доступен только root",
        ],
        "correct": 0,
        "explanation": (
            "6 = 4 (чтение) + 2 (запись) для владельца. 4 = только чтение для "
            "группы и 4 — для остальных. Получается rw-r--r--. Обычная запись "
            "для конфигурационных файлов."
        ),
        "sample": "644 = rw-r--r--.",
    },
    {
        "id": "m6-12",
        "module": 6,
        "topic": "Поиск в файлах",
        "difficulty": 2,
        "type": "input",
        "prompt": "Какой командой найти строки со словом error в файле app.log?",
        "answer_kind": "text",
        "answers": ["grep error app.log", "grep -i error app.log", "grep 'error' app.log", "grep \"error\" app.log"],
        "explanation": (
            "grep ищет строки по шаблону. Команда grep error app.log выведет "
            "строки, содержащие error. Ключ -i игнорирует регистр."
        ),
        "sample": "grep error app.log",
    },
]
