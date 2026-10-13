import unittest

from app.services.pre_gpt_pipeline import parse_sheet_rows
from app.services.sheet_columns import (
    duplicate_columns, index_to_letter, task_work_day,
)


def sample_rows():
    header = ['需求人员', '主播名称', '中文内容', '外文内容', '需求说明', '主播图片链接', '日期', '', '', 'J列', '作者', '制作情况']
    return [
        header,
        ['批量制作中'],
        [
            '李四', '主播', '你好', 'Habari', '闭眼',
            'https://drive.google.com/drive/folders/decoy', '2026/10/13', '', '',
            'https://drive.google.com/drive/folders/realj', '', '',
        ],
        ['批量已完成'],
    ]


class SheetColumnTests(unittest.TestCase):
    def test_template_keeps_image_links_on_column_j(self):
        parsed = parse_sheet_rows(sample_rows(), {'mode': 'template', 'columns': {}})
        task = parsed['tasks'][0]
        self.assertEqual(task['主播图片链接'], 'https://drive.google.com/drive/folders/realj')
        self.assertEqual(task['模式'], 'PRAYING')
        self.assertEqual(parsed['header_map']['主播图片链接'], 9)
        self.assertNotIn('日期', task)

    def test_custom_columns_read_image_copy_and_date(self):
        spec = {'mode': 'custom', 'columns': {
            '需求人员': '0', '主播名称': '1', '中文内容': '2', '外文内容': '3',
            '需求说明': '4', '主播图片链接': '5', '日期': '6',
            '作者': 'header', '制作情况': 'header',
        }}
        parsed = parse_sheet_rows(sample_rows(), spec)
        task = parsed['tasks'][0]
        self.assertEqual(task['主播图片链接'], 'https://drive.google.com/drive/folders/decoy')
        self.assertEqual(task['外文内容'], 'Habari')
        self.assertEqual(task['日期'], '2026-10-13')
        self.assertEqual(parsed['write_header_map']['作者'], 10)
        self.assertEqual(parsed['write_header_map']['制作情况'], 11)

    def test_custom_header_choice_finds_the_named_column(self):
        spec = {'mode': 'custom', 'columns': {
            '主播名称': 'header', '外文内容': 'header', '主播图片链接': 'unused', '日期': 'unused',
        }}
        parsed = parse_sheet_rows(sample_rows(), spec)
        task = parsed['tasks'][0]
        self.assertEqual(task['主播名称'], '主播')
        self.assertEqual(task['外文内容'], 'Habari')
        self.assertEqual(task['主播图片链接'], '')
        self.assertEqual(task['日期'], '')

    def test_custom_requires_host_and_foreign_copy(self):
        spec = {'mode': 'custom', 'columns': {'主播名称': '1', '外文内容': 'unused'}}
        with self.assertRaises(ValueError) as caught:
            parse_sheet_rows(sample_rows(), spec)
        self.assertIn('外文文案', str(caught.exception))

    def test_letters_dates_and_duplicate_columns(self):
        self.assertEqual(index_to_letter(0), 'A')
        self.assertEqual(index_to_letter(9), 'J')
        self.assertEqual(index_to_letter(26), 'AA')
        self.assertEqual(task_work_day('2026/10/01', '2026-10-13'), '2026-10-01')
        self.assertEqual(task_work_day('', '2026-10-13T08:00:00'), '2026-10-13')
        self.assertEqual(task_work_day('不是日期', '2026-10-13'), '2026-10-13')
        dupes = duplicate_columns({'主播图片链接': '9', '日期': '9', '外文内容': 'header'})
        self.assertEqual(dupes, ['J 列：图片链接、日期'])


if __name__ == '__main__':
    unittest.main()
