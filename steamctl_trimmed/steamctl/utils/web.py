import requests

def make_requests_session():
    """Return a requests.Session with necessary headers"""
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Valve/Steam HTTP Client 1.0 (ValveSteamClient)',
    })
    return session 