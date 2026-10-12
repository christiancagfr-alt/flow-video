import tempfile,unittest,wave
from pathlib import Path
from app.services.asr_gaps import uncovered_intervals,audible_gaps,insert_gap_words

class GapTests(unittest.TestCase):
    def test_middle_gap_not_hidden_by_final_word(self):
        words=[{'start':0,'end':70},{'start':100,'end':196}]
        self.assertEqual(uncovered_intervals(words,196),[(70,100)])

    def test_audible_gap_distinguished_from_silence(self):
        import math,struct
        rate=16000
        with tempfile.TemporaryDirectory() as directory:
            file=Path(directory)/'audio.wav'
            with wave.open(str(file),'wb') as wav:
                wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(rate)
                wav.writeframes(b''.join(struct.pack('<h',int(4000*math.sin(i*2*math.pi*220/rate)) if 3*rate<=i<6*rate else 0) for i in range(rate*9)))
            self.assertEqual(audible_gaps(file,[{'start':0,'end':3},{'start':6,'end':7}]),[(3,6)])

    def test_recovery_keeps_previous_words_and_clips_context(self):
        first=[{'words':[{'start':0,'end':1,'text':'keep'},{'start':4,'end':5,'text':'also'}]}]
        new=[{'words':[{'start':.1,'end':.9,'text':'context'},{'start':1.5,'end':2.5,'text':'recovered'}]}]
        result=insert_gap_words(first,new,[(1,4)])
        self.assertEqual([w['text'] for w in result[0]['words']],['keep','recovered','also'])

if __name__=='__main__':unittest.main()
