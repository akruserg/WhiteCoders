"""Нагрузочная проверка требований ТЗ: отклик до 2 с при 100 пользователях и не
менее 20 одновременных сессий.

Каждый виртуальный пользователь входит в систему и в цикле проходит карточку:
выдача -> принять вызов -> черновик -> отправка. Показывает задержки по
операциям (p50/p95/max), число ошибок и пропускную способность.

Подготовка: преподаватель создает и запускает занятие, в него добавлены
обучающиеся. Файл users.csv: строки "логин,пароль" (по числу пользователей).

    python tools/loadtest.py --base https://localhost --session <uuid> \
        --users-file users.csv --users 20 --duration 120 --insecure

Параметр --ramp 15 подключает пользователей плавно за 15 секунд (обычная утренняя
картина); без него все входят в одну секунду, это худший случай.
"""

import argparse
import csv
import statistics
import threading
import time
from collections import defaultdict

import httpx

LIMIT_P95_SEC = 2.0  # ТЗ: время отклика интерфейса не более 2 секунд


class Stats:
    def __init__(self):
        self.lock = threading.Lock()
        self.times = defaultdict(list)
        self.errors = defaultdict(int)

    def add(self, name, seconds, ok):
        with self.lock:
            self.times[name].append(seconds)
            if not ok:
                self.errors[name] += 1


def timed(stats, client, name, method, url, **kwargs):
    started = time.perf_counter()
    try:
        response = client.request(method, url, **kwargs)
        ok = response.status_code < 400
    except httpx.HTTPError:
        response, ok = None, False
    stats.add(name, time.perf_counter() - started, ok)
    return response if ok else None


def fill(template_fields):
    return {f["key"]: "нагрузочный тест" for f in template_fields}


def virtual_user(args, credentials, stats, stop_at):
    username, password = credentials
    with httpx.Client(
        base_url=args.base + "/api/v1", verify=not args.insecure, timeout=60
    ) as client:
        login = timed(
            stats,
            client,
            "login",
            "POST",
            "/auth/login",
            json={"username": username, "password": password},
        )
        if login is None:
            return
        client.headers["Authorization"] = "Bearer " + login.json()["access_token"]
        while time.time() < stop_at:
            card = timed(
                stats,
                client,
                "next_card",
                "POST",
                f"/sessions/{args.session}/attempts/next",
            )
            if card is None:
                time.sleep(1)
                continue
            data = card.json()
            attempt = data["attempt"]["id"]
            timed(stats, client, "answer", "POST", f"/attempts/{attempt}/answer")
            answer = fill(data.get("template_fields", []))
            timed(
                stats,
                client,
                "draft",
                "PUT",
                f"/attempts/{attempt}/draft",
                json={"answer": answer, "actions": []},
            )
            timed(
                stats,
                client,
                "submit",
                "POST",
                f"/attempts/{attempt}/submit",
                json={"answer": answer, "actions": []},
            )


def percentile(values, p):
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(len(ordered) * p))]


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--base", required=True, help="например https://localhost")
    parser.add_argument("--session", required=True, help="UUID запущенного занятия")
    parser.add_argument("--users-file", required=True)
    parser.add_argument("--users", type=int, default=20)
    parser.add_argument("--duration", type=int, default=120, help="секунд")
    parser.add_argument(
        "--ramp",
        type=int,
        default=0,
        help="за сколько секунд плавно подключить всех (0 - все сразу, худший случай: "
        "вход тяжелый, пароль хэшируется PBKDF2)",
    )
    parser.add_argument(
        "--insecure", action="store_true", help="не проверять сертификат (стенд)"
    )
    args = parser.parse_args()

    with open(args.users_file, encoding="utf-8") as handle:
        credentials = [tuple(row[:2]) for row in csv.reader(handle) if row][
            : args.users
        ]
    stats, stop_at = Stats(), time.time() + args.duration
    threads = [
        threading.Thread(target=virtual_user, args=(args, c, stats, stop_at))
        for c in credentials
    ]
    started = time.time()
    for index, t in enumerate(threads):
        t.start()
        if args.ramp and index + 1 < len(threads):
            time.sleep(args.ramp / len(threads))
    for t in threads:
        t.join()
    elapsed = time.time() - started

    print(f"Пользователей: {len(credentials)}, время: {elapsed:.0f} с\n")
    print(
        f"{'операция':<12}{'запросов':>9}{'ошибок':>8}{'p50, с':>9}{'p95, с':>9}{'max, с':>9}"
    )
    worst = 0.0
    for name, values in stats.times.items():
        p95 = percentile(values, 0.95)
        worst = max(worst, p95)
        print(
            f"{name:<12}{len(values):>9}{stats.errors[name]:>8}{statistics.median(values):>9.2f}{p95:>9.2f}{max(values):>9.2f}"
        )
    total = sum(len(v) for v in stats.times.values())
    print(f"\nПропускная способность: {total / elapsed:.1f} запросов/с")
    verdict = (
        "ВЫПОЛНЕНО"
        if worst <= LIMIT_P95_SEC and not sum(stats.errors.values())
        else "НЕ ВЫПОЛНЕНО"
    )
    print(f"Требование ТЗ (p95 не более {LIMIT_P95_SEC} с, без ошибок): {verdict}")


if __name__ == "__main__":
    main()
