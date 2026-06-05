class SessionModel:
    def __init__(self, **kwargs): pass
    def generate_authcode(self): return "https://mock.fyers.login"
    def set_token(self, token): pass
    def generate_token(self): return {"access_token": "mock"}

class FyersModel:
    SessionModel = SessionModel

fyersModel = FyersModel
