"""動画を YouTube にアップロードする。

使い方:
    python upload.py auth                 # 最初の1回（と、テスト中なら7日ごと）: ブラウザで許可する
    python upload.py 20261028             # out/20261028/ の動画・サムネイル・概要欄をアップ（非公開）
    python upload.py 20261028 unlisted    # 公開範囲を指定（private / unlisted / public）
    python upload.py 20261028_night       # 夜の版
    python upload.py captions 20261028_fund   # アップ済みの動画に字幕（captions.srt）だけ付ける

認証の情報は secrets/ に置く（client_secret.json は Google Cloud から、token.json はこのスクリプトが作る）。
API の審査が通るまでは、どの公開範囲を指定しても YouTube 側で非公開に固定される。
字幕の登録には youtube.force-ssl の許可が要る。古い token.json（アップロードだけの許可）のままなら、
動画のアップロードは続けて字幕だけ飛ばす（auth をやり直すと付くようになる）。
"""
import json
import sys
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).parent
SECRETS = ROOT / "secrets"
CLIENT = SECRETS / "client_secret.json"
TOKEN = SECRETS / "token.json"
SCOPES = ["https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube.force-ssl"]
CAPTION_SCOPE = SCOPES[1]
CATEGORY = "25"  # ニュースと政治


def credentials(interactive=False):
    creds = None
    if TOKEN.exists() and not interactive:
        creds = Credentials.from_authorized_user_file(str(TOKEN))  # 許可した範囲は token.json に書いてあるものを使う
    if creds and creds.valid:
        return creds
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            TOKEN.write_text(creds.to_json(), encoding="utf-8")
            return creds
        except Exception as e:
            if not interactive:
                sys.exit(f"トークンの更新に失敗しました（{e}）。python upload.py auth で許可し直してください。")
    if not interactive:
        sys.exit("まだ許可されていません。python upload.py auth を実行してください。")
    flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT), SCOPES)
    creds = flow.run_local_server(port=0, prompt="consent",
                                  success_message="許可できました。このタブを閉じてください。")
    TOKEN.write_text(creds.to_json(), encoding="utf-8")
    return creds


def upload(date, privacy="private"):
    out = ROOT / "out" / date
    script = json.loads((out / "script.json").read_text(encoding="utf-8"))
    video = out / f"market_{date}.mp4"
    thumb = out / "thumbnail.jpg"
    description = (out / "description.txt").read_text(encoding="utf-8")
    # 概要欄の1行目はタイトルなので省く。YouTube の上限は5,000バイト
    description = description.split("\n", 1)[1].strip() if description.startswith(script["title"]) else description
    description = description.encode("utf-8")[:4900].decode("utf-8", "ignore")

    creds = credentials()
    yt = build("youtube", "v3", credentials=creds)
    body = {
        "snippet": {
            "title": script["title"][:100],
            "description": description,
            "tags": script.get("tags", []),
            "categoryId": CATEGORY,
            "defaultLanguage": "ja",
            "defaultAudioLanguage": "ja",
        },
        "status": {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": False,
            "containsSyntheticMedia": True,  # 原稿と音声を AI で作っているため
        },
    }
    req = yt.videos().insert(part="snippet,status", body=body,
                             media_body=MediaFileUpload(str(video), chunksize=8 * 1024 * 1024, resumable=True))
    resp = None
    while resp is None:
        status, resp = req.next_chunk()
        if status:
            print(f"  {int(status.progress() * 100)}%")
    vid = resp["id"]
    print(f"アップロード完了: https://youtu.be/{vid}  （公開範囲: {resp['status']['privacyStatus']}）")
    if thumb.exists():
        try:
            yt.thumbnails().set(videoId=vid, media_body=MediaFileUpload(str(thumb))).execute()
            print("サムネイルを設定しました")
        except Exception as e:
            print(f"サムネイルを設定できませんでした（電話番号の確認が済んでいないと失敗します）: {e}")
    (out / "upload.json").write_text(json.dumps({"id": vid, "privacy": resp["status"]["privacyStatus"]},
                                                ensure_ascii=False), encoding="utf-8")
    add_captions(yt, creds, vid, out)
    return vid


def add_captions(yt, creds, vid, out):
    srt = out / "captions.srt"
    if not srt.exists():
        return
    if CAPTION_SCOPE not in (creds.scopes or []):
        print("字幕は付けませんでした（許可が足りません。python upload.py auth をやり直してください）")
        return
    try:
        yt.captions().insert(part="snippet", body={"snippet": {"videoId": vid, "language": "ja", "name": "日本語",
                                                               "isDraft": False}},
                             media_body=MediaFileUpload(str(srt), mimetype="application/octet-stream")).execute()
        print("字幕を付けました")
    except Exception as e:
        print(f"字幕を付けられませんでした: {e}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    if sys.argv[1] == "auth":
        credentials(interactive=True)
        print("許可できました:", TOKEN)
    elif sys.argv[1] == "captions":
        out = ROOT / "out" / sys.argv[2]
        vid = json.loads((out / "upload.json").read_text(encoding="utf-8"))["id"]
        creds = credentials()
        add_captions(build("youtube", "v3", credentials=creds), creds, vid, out)
    else:
        upload(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "private")
