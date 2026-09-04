# reference/

실험 PC ↔ 개발 PC 가 **git 으로 공유**하는 참고 자료 폴더.
(Claude 가 참고하기 좋은 형식으로 넣을 것.)

## 넣는 형식
- ⭐ 권장: `.py` `.md` `.txt` `.csv` — Claude 가 바로 읽고 검색 가능
- ⭕ 가능: `.pdf` — 추출해서 읽음(텍스트 PDF만)
- ⚠️ 지양: `.mat` `.dll` 등 대용량 바이너리 — git 이 무거워짐(원본은 docs/ 같은 미추적 폴더에)

## 동기화

**파일을 넣은 PC에서 (보내기):**
```cmd
git pull origin main
git add reference/
git commit -m "reference: 무엇을 넣었는지"
git push origin main
```

**받는 PC에서:**
```cmd
git pull origin main
```

## 내용 인덱스 (넣을 때 한 줄씩 적어두면 찾기 쉬움)
- (예) `firehawk_notes.md` — RTPS/phase_cal 관련 메모
