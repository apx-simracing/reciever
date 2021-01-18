from flask import Flask, request, Request, abort, send_file, jsonify, render_template
from flask_caching import Cache
from functools import wraps
from werkzeug.exceptions import HTTPException
from rf2.startup import stop_server, oneclick_start_server
from rf2.status import get_server_status
from rf2.interaction import do_action, Action, kick_player, chat
from rf2.deploy import deploy_server, VERSION_SUFFIX
from rf2.results import get_results, get_replays
from rf2.setup import install_server
from rf2.util import create_config
from os.path import join, exists
from os import mkdir, unlink
from shutil import rmtree, unpack_archive
from json import loads
from time import sleep, time
from math import ceil
from shutil import copytree
from sys import exit
import threading
from pathlib import Path

app = Flask(__name__)
config = {"DEBUG": True, "CACHE_TYPE": "simple", "CACHE_DEFAULT_TIMEOUT": 20}

app.config.from_mapping(config)
cache = Cache(app)

recieved_status = None

# @app.errorhandler(Exception)


def read_mod_config() -> dict:
    config = None
    if not exists("mod.json"):
        return config
    with open("mod.json", "r") as file:
        config = loads(file.read())
    return config


def read_webserver_config() -> dict:
    server_config_path = str(Path(__file__).absolute()).replace(
        "reciever.py", "server.json"
    )
    if not exists(server_config_path):
        raise Exception("Server config was not found")
    config = None
    with open(server_config_path, "r") as file:
        config = loads(file.read())
    return config


def get_server_config() -> dict:
    return {"mod": read_mod_config(), "server": read_webserver_config()}


def check_api_key(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        config = read_webserver_config()
        api_key = request.headers.get("Authorization")
        if not api_key or api_key != config["auth"]:
            abort(403)
        return f(*args, **kwargs)

    return decorated_function


def json_response(data) -> str:
    result = jsonify(data)
    return result


def handle_error(e):
    code = 500
    print(e)
    if isinstance(e, HTTPException):
        code = e.code
    return json_response({"error": str(e)}), code


@app.route("/oneclick_start_server", methods=["GET"])
@check_api_key
def start_oneclick():
    got = oneclick_start_server(get_server_config())
    if not got:
        raise Exception("The server could not be started")
    return json_response({"is_ok": got}), 200


@app.route("/status", methods=["GET"])
def status():
    got = get_server_status(get_server_config())
    return json_response(got), 200


@app.route("/stop", methods=["GET"])
@check_api_key
def stop():
    return json_response({"is_ok": stop_server(get_server_config())}), 200


@app.route("/action/<action>", methods=["POST"])
@check_api_key
def action(action: str):
    is_ok = False
    for key in Action.__dict__.keys():
        if action.lower() == str(key).lower():
            do_action(get_server_config(), Action[key].value)
            is_ok = True
            break
    return json_response({"is_ok": is_ok})


@app.route("/kick", methods=["POST"])
@check_api_key
def kick():
    is_ok = False
    name = request.form.get("driver")
    if not name:
        abort(404)
    kick_player(get_server_config(), name)
    is_ok = True
    return json_response({"is_ok": is_ok})


@app.route("/chat", methods=["POST"])
@check_api_key
def send_message():
    message = request.form.get("message")
    from rf2.interaction import chat

    if not message:
        abort(404)
    chat(get_server_config(), message)
    return json_response({"is_ok": True})


@app.route("/deploy", methods=["POST"])
def deploy_server_config():
    config_contents = request.form.get("config")
    rfm_contents = request.form.get("rfm_config")
    if not config_contents:
        abort(404)
    try:
        loads(config_contents)
    except JSONDecodeError:
        return json_response({"is_ok": False, "syntax_failed": True})

    # apply weather and grip conditions
    weather = None
    grip = {}
    for key, value in request.files.items():
        if "RealRoad" in key:
            # it is a grip file
            grip[key] = value
        if key == "weather":
            weather = value
    # paste the config
    with open("mod.json", "w") as config:
        config.write(config_contents)
    from rf2.deploy import deploy_server

    got = deploy_server(get_server_config(), rfm_contents, weather, grip)
    return json_response({"is_ok": False})


@app.route("/results", methods=["GET"])
def get_server_results():
    results = get_results(get_server_config())
    replays = get_replays(get_server_config())
    return json_response({"results": results, "replays": replays})


@app.route("/process_results", methods=["GET"])
def return_processed_results():
    got = process_results()
    return json_response(got)


@app.route("/skins", methods=["POST"])
@check_api_key
def get_skins():
    config = get_server_config()
    build_path = join(config["server"]["root_path"], "build")
    if request.method == "POST":
        if "skins" not in request.files or "target_path" not in request.form:
            abort(418)
        file = request.files["skins"]
        skinpack_path = join(build_path, file.filename)
        got = file.save(skinpack_path)

        target_path = join(build_path, request.form.get("target_path"))
        if exists(target_path):
            rmtree(target_path)
        mkdir(target_path)

        unpack_archive(skinpack_path, target_path)
        unlink(skinpack_path)
    return json_response({"is_ok": True})


@app.route("/install", methods=["GET"])
def initial_setup():
    got = install_server(get_server_config())
    return json_response({"is_ok": got})


@app.route("/lockfile", methods=["GET"])
def get_lockfile():
    server_config = get_server_config()
    root_path = server_config["server"]["root_path"]
    lockfile_path = join(root_path, "server", "UserData", "ServerKeys.bin")
    if not exists(lockfile_path):
        abort(404)
    return send_file(
        lockfile_path, attachment_filename="ServerKeys.bin", as_attachment=True
    )


@app.route("/unlock", methods=["POST"])
def initial_setup_unlock():
    if request.method == "POST":
        if "unlock" not in request.files:
            abort(418)
        file = request.files["unlock"]
        server_config = get_server_config()
        root_path = server_config["server"]["root_path"]
        unlock_path = join(root_path, "server", "UserData", "ServerUnlock.bin")
        file.save(unlock_path)
        return "ok"
    return "fail"


def get_public_mod_info():
    got = get_server_config()
    print(got)
    if got is None:
        return None
    del got["mod"]["server"]
    del got["mod"]["mod"]["rfm"]
    del got["server"]

    return got


@app.route("/current", methods=["GET"])
def current_mod_html():
    got = get_public_mod_info()
    if got is None:
        abort(404)

    has_updates = True
    for source, car in got["mod"]["cars"].items():
        if car["component"]["update"]:
            has_updates = True
    return render_template(
        "current.html", data=got, suffix=VERSION_SUFFIX, has_updates=has_updates
    )


@app.after_request
def after_request_func(response):
    response.headers.add("Access-Control-Allow-Headers", "Content-Type")
    response.headers.add("Access-Control-Allow-Origin", "*")
    response.headers.add("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
    return response


if __name__ == "__main__":
    server_config_path = str(Path(__file__).absolute()).replace(
        "reciever.py", "server.json"
    )
    if not exists(server_config_path):
        print("{} is not present".format(server_config_path))
        create_config()
        exit(127)
    webserver_config = read_webserver_config()

    root_path = webserver_config["root_path"]
    reciever_path = join(root_path, "reciever")

    manifests_target_path = join(reciever_path, "templates", "Manifests")
    installed_target_path = join(reciever_path, "templates", "Installed")

    if not exists(manifests_target_path):
        manifests_source_path = join(root_path, "server", "Manifests")
        copytree(manifests_source_path, manifests_target_path)
        print("Created manifest template")

    if not exists(installed_target_path):
        installed_source_path = join(root_path, "server", "Installed")
        copytree(installed_source_path, installed_target_path)
        print("Created installed template")

    app.run(
        host=webserver_config["host"],
        port=webserver_config["port"],
        debug=webserver_config["debug"],
    )
