"""The Google Sheet behind the catalogue, reached through its Apps Script web app (sheet.gs).

The Sheet itself stays private: only this endpoint can see it, and only with the secret. Set both
SHEET_URL (the script's /exec URL) and SHEET_SECRET in the environment - on Vercel as project
environment variables, and locally in the shell before running build.py or admin.py.

Rows come back as the sheet displays them: a list of lists of strings, row 0 being the header.
Every index here is a zero-based data row, counted after that header; sheet.gs maps it back.
"""
import json, os, urllib.parse, urllib.request


def url():
    return os.environ.get("SHEET_URL", "")


def secret():
    return os.environ.get("SHEET_SECRET", "")


def configured():
    return bool(url() and secret())


def call(body=None):
    """GET the rows when body is None, otherwise POST the operation. Returns the decoded reply.

    Apps Script answers a POST with a redirect to googleusercontent, and urllib follows it as a GET.
    That is fine and is how everyone talks to these: the write already happened before the redirect.
    """
    if not configured():
        raise RuntimeError("SHEET_URL and SHEET_SECRET are not set, so the catalogue cannot be reached")
    if body is None:
        target = url() + ("&" if "?" in url() else "?") + urllib.parse.urlencode({"secret": secret()})
        request = urllib.request.Request(target)
    else:
        request = urllib.request.Request(
            url(), data=json.dumps(dict(body, secret=secret())).encode("utf-8"),
            headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=30) as reply:
        answer = json.load(reply)
    if answer.get("error"):
        raise RuntimeError(f"the sheet said: {answer['error']}")
    return answer


def rows():
    """Every row of the sheet, header first."""
    return call()["rows"]


def write(index, values):
    """Overwrite data row `index`, or append when it is None. Returns the sheet as it now stands."""
    return call({"op": "write", "index": index, "values": values})["rows"]


def delete(index):
    """Remove data row `index`. Returns the sheet as it now stands."""
    return call({"op": "delete", "index": index})["rows"]
