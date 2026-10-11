import unittest,tempfile,struct
from pathlib import Path
from app.core.daily_statistics import summarize,movie_duration
class DailyStatisticsTests(unittest.TestCase):
    def row(self,day,name='A',status='',path='clip.mp4'):
        return dict(work_date=day,recipient_name=name,edit_status=status,upload_status='',edit_output_path=path)
    def test_current_cohort_and_all_date_backlog(self):
        rows=[self.row('2026-10-10',status='已导出'),self.row('2026-10-10'),self.row('2026-10-09'),self.row('2026-10-09',status='已完成')]
        d=summarize(rows,'2026-10-10',lambda p:61.5)
        self.assertEqual((d['total'],d['completed'],d['unfinished'],d['rate'],d['backlog']),(2,1,1,.5,2))
        self.assertEqual(d['seconds'],61.5);self.assertEqual(len(d['recipients']),1);self.assertEqual(d['recipients'][0]['backlog'],2)
    def test_stale_export_path_does_not_mark_complete(self):
        d=summarize([self.row('2026-10-10',status='导出失败')],'2026-10-10',lambda p:100)
        self.assertEqual(d['completed'],0);self.assertEqual(d['seconds'],0)
    def test_unknown_duration_and_empty_day(self):
        rows=[self.row('2026-10-09',status='已导出'),self.row('2026-10-09',name='B')]
        d=summarize(rows,'2026-10-09',lambda p:None);self.assertEqual(d['duration_missing'],1);self.assertEqual(d['completed'],1)
        d=summarize(rows,'2026-10-10',lambda p:None);self.assertEqual((d['total'],d['rate'],d['backlog']),(0,0,1))
    def test_actual_movie_header_versions_and_bad_files(self):
        def box(kind,data):return struct.pack('>I4s',len(data)+8,kind)+data
        with tempfile.TemporaryDirectory() as folder:
            for version,data in [(0,b'\0'*12+struct.pack('>II',1000,65432)),(1,b'\1'+b'\0'*19+struct.pack('>IQ',1000,65432))]:
                p=Path(folder)/f'{version}.mp4';p.write_bytes(box(b'ftyp',b'isom')+box(b'moov',box(b'mvhd',data)))
                original=p.read_bytes();self.assertAlmostEqual(movie_duration(p),65.432);self.assertEqual(p.read_bytes(),original)
            bad=Path(folder)/'bad.mp4';bad.write_bytes(b'broken');self.assertIsNone(movie_duration(bad));self.assertIsNone(movie_duration(Path(folder)/'missing'))
if __name__=='__main__':unittest.main()
