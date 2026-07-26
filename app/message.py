def success(request, message):
    request.session["success"] = message


def error(request, message):
    request.session["error"] = message


def warning(request, message):
    request.session["warning"] = message