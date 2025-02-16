import html
import urllib.parse

from django.core import signing
from django.http import HttpResponseBadRequest, HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse


def _is_samesite_referer(request):
    referer = request.headers.get("referer")
    if referer is None:
        return False

    referer = urllib.parse.urlparse(referer)

    # Make sure we have a valid URL for Referer.
    if "" in (referer.scheme, referer.netloc):
        return False

    return (referer.scheme, referer.netloc) == (request.scheme, request.get_host())


def redirect_view(request):
    signer = signing.Signer(salt="safe-redirect")
    try:
        url = signer.unsign(request.GET.get("url", ""))
    except signing.BadSignature:
        return HttpResponseBadRequest("Invalid parameter")

    if not _is_samesite_referer(request):
        u = urllib.parse.urlparse(url)
        return render(
            request,
            "common/redirect.html",
            {
                "hostname": u.hostname,
                "url": url,
            },
        )
    # As most of our URLs are rendered via Markdown, they may contain
    # HTML entities – particularly, ampersands will be encoded as "&amp;".
    url = html.unescape(url)
    return HttpResponseRedirect(url)


def safelink(url):
    signer = signing.Signer(salt="safe-redirect")
    return reverse("redirect") + "?url=" + urllib.parse.quote(signer.sign(url))
