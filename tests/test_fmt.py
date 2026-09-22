import unittest

from study import fmt


class NamesTest(unittest.TestCase):
    def test_parse_lab_with_topic(self):
        p = fmt.parse_name("Сдать отчет по лабораторной работе № 2. Простые сети в GNS3")
        self.assertEqual(p, {"work": "lab", "num": "2", "topic": "Простые сети в GNS3"})

    def test_parse_variants(self):
        self.assertEqual(fmt.parse_name("Загрузка 3 лабораторной работы")["num"], "3")
        self.assertEqual(fmt.parse_name('Сдать отчёт по домашней работе №1 "Кодирование"'),
                         {"work": "hw", "num": "1", "topic": "Кодирование"})
        self.assertEqual(fmt.parse_name("Выбрать тему доклада к лекции 3")["work"], "topic")
        self.assertEqual(fmt.parse_name("Сдать доклад. Лекция 4")["work"], "talk")
        self.assertEqual(fmt.parse_name("Пересдача лабораторной работы № 3"),
                         {"work": "retake", "num": "3", "topic": ""})
        self.assertEqual(fmt.parse_name("Решение задачи 5 ИДЗ"),
                         {"work": "task", "num": "5", "topic": ""})
        self.assertEqual(fmt.short_name("Решение задачи 5 ИДЗ"), "Задача 5")
        self.assertIsNone(fmt.parse_name("Тест после лекции №1"))
        self.assertIsNone(fmt.parse_name(None))

    def test_short_name(self):
        name = "Сдать отчет по лабораторной работе № 2. Простые сети"
        self.assertEqual(fmt.short_name(name), "ЛР 2 — Простые сети")
        self.assertEqual(fmt.short_name(name, tail=False), "ЛР 2")
        self.assertEqual(fmt.short_name("Доклад к лекции 4"), "Доклад к лекции 4")
        self.assertEqual(fmt.short_name("Пересдача лабораторной работы № 3"), "Пересдача ЛР 3")
        self.assertEqual(fmt.short_name("<b>Тест</b> &amp; ещё"), "Тест & ещё")
        self.assertEqual(fmt.plain("<p>Нет <b>схемы</b>.</p><p>Срок: 1 <i>день</i>!</p>"),
                         "Нет схемы. Срок: 1 день!")
        self.assertEqual(len(fmt.short_name("x" * 100)), 61)   # 60 символов и многоточие


class TimeTest(unittest.TestCase):
    def test_left(self):
        self.assertEqual(fmt.left(-1), "срок прошёл")
        self.assertEqual(fmt.left(59), "меньше часа")
        self.assertEqual(fmt.left(2 * fmt.HOUR + 1), "2 ч")
        self.assertEqual(fmt.left(3 * fmt.DAY), "3 дн")

    def test_moment(self):
        self.assertIsNone(fmt.moment(0))
        m = fmt.moment(1_000_000, now=1_000_000 - fmt.DAY)
        self.assertEqual((m["ts"], m["left"], m["left_sec"], m["overdue"]),
                         (1_000_000, "1 дн", fmt.DAY, False))
        self.assertTrue(fmt.moment(1_000_010, now=1_000_020)["overdue"])   # <0 на Windows нельзя
        # ts=1 даёт --since all; на Windows astimezone() naive-времени первых часов эпохи
        # падал OSError 22 (#1) — CI на windows-latest это поймает
        self.assertEqual(fmt.moment(1)["ts"], 1)
        self.assertTrue(fmt.moment(1)["iso"].startswith("1970-01-01T"))


class TablesTest(unittest.TestCase):
    def test_md_table(self):
        self.assertEqual(fmt.md_table([["a", 1]], ["x", "yy"]),
                         "| x | yy |\n| --- | --- |\n| a | 1 |")

    def test_table(self):
        self.assertEqual(fmt.table([]), "")
        self.assertEqual(fmt.table([["a", "bbb"], ["cc", "d"]], ["1", "2"]),
                         "1   2\n--  ---\na   bbb\ncc  d")


if __name__ == "__main__":
    unittest.main()
