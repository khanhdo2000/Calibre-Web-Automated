# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2025 Calibre-Web contributors
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

# custom jinja filters

from markupsafe import escape
import datetime
import mimetypes
from uuid import uuid4

from flask import Blueprint, request, url_for, g
from flask_babel import format_date
from .cw_login import current_user

from . import constants, logger, config

jinjia = Blueprint('jinjia', __name__)
log = logger.create()


# pagination links in jinja
@jinjia.app_template_filter('url_for_other_page')
def url_for_other_page(page):
    args = request.view_args.copy()
    args['page'] = page
    for get, val in request.args.items():
        args[get] = val
    return url_for(request.endpoint, **args)


# shortentitles to at longest nchar, shorten longer words if necessary
@jinjia.app_template_filter('shortentitle')
def shortentitle_filter(s, nchar=20):
    text = s.split()
    res = ""  # result
    suml = 0  # overall length
    for line in text:
        if suml >= 60:
            res += '...'
            break
        # if word longer than 20 chars truncate line and append '...', otherwise add whole word to result
        # string, and summarize total length to stop at chars given by nchar
        if len(line) > nchar:
            res += line[:(nchar-3)] + '[..] '
            suml += nchar+3
        else:
            res += line + ' '
            suml += len(line) + 1
    return res.strip()


@jinjia.app_template_filter('mimetype')
def mimetype_filter(val):
    return mimetypes.types_map.get('.' + val, 'application/octet-stream')


@jinjia.app_template_filter('formatdate')
def formatdate_filter(val):
    try:
        return format_date(val, format='medium')
    except AttributeError as e:
        log.error('Babel error: %s, Current user locale: %s, Current User: %s', e,
                  current_user.locale,
                  current_user.name
                  )
        return val


@jinjia.app_template_filter('formatdateinput')
def format_date_input(val):
    input_date = val.isoformat().split('T', 1)[0]  # Hack to support dates <1900
    return '' if input_date == "0101-01-01" else input_date


@jinjia.app_template_filter('strftime')
def timestamptodate(date, fmt=None):
    date = datetime.datetime.fromtimestamp(
        int(date)/1000
    )
    native = date.replace(tzinfo=None)
    if fmt:
        time_format = fmt
    else:
        time_format = '%d %m %Y - %H:%S'
    return native.strftime(time_format)


@jinjia.app_template_filter('yesno')
def yesno(value, yes, no):
    return yes if value else no


@jinjia.app_template_filter('formatfloat')
def formatfloat(value, decimals=1):
    if not value:
        return value
    try:
        # Convert to float if it's a string (series_index is stored as String in DB)
        float_value = float(value) if isinstance(value, str) else value
        formated_value = ('{0:.' + str(decimals) + 'f}').format(float_value)
        if formated_value.endswith('.' + "0" * decimals):
            formated_value = formated_value.rstrip('0').rstrip('.')
        return formated_value
    except (ValueError, TypeError):
        # If conversion fails, return the original value
        return value


'''@jinjia.app_template_filter('formatseriesindex')
def formatseriesindex_filter(series_index):
    if series_index:
        try:
            if int(series_index) - series_index == 0:
                return int(series_index)
            else:
                return series_index
        except (ValueError, TypeError):
            return series_index
    return 0
'''


@jinjia.app_template_filter('escapedlink')
def escapedlink_filter(url, text):
    return "<a href='{}'>{}</a>".format(url, escape(text))


@jinjia.app_template_filter('uuidfilter')
def uuidfilter(var):
    return uuid4()


@jinjia.app_template_filter('cache_timestamp')
def cache_timestamp(rolling_period='month'):
    if rolling_period == 'day':
        return str(int(datetime.datetime.today().replace(hour=1, minute=1).timestamp()))
    elif rolling_period == 'year':
        return str(int(datetime.datetime.today().replace(day=1).timestamp()))
    else:
        return str(int(datetime.datetime.today().replace(month=1, day=1).timestamp()))


@jinjia.app_template_filter('last_modified')
def book_last_modified(book):
    return str(int(book.last_modified.timestamp()))


@jinjia.app_template_filter('get_cover_srcset')
def get_cover_srcset(book):
    srcset = list()
    resolutions = {
        constants.COVER_THUMBNAIL_SMALL: 'sm',
        constants.COVER_THUMBNAIL_MEDIUM: 'md',
        constants.COVER_THUMBNAIL_LARGE: 'lg'
    }
    for resolution, shortname in resolutions.items():
        url = url_for('web.get_cover', book_id=book.id, resolution=shortname, c=book_last_modified(book))
        srcset.append(f'{url} {resolution}x')
    return ', '.join(srcset)


@jinjia.app_template_filter('get_series_srcset')
def get_cover_srcset(series):
    srcset = list()
    resolutions = {
        constants.COVER_THUMBNAIL_SMALL: 'sm',
        constants.COVER_THUMBNAIL_MEDIUM: 'md',
        constants.COVER_THUMBNAIL_LARGE: 'lg'
    }
    for resolution, shortname in resolutions.items():
        url = url_for('web.get_series_cover', series_id=series.id, resolution=shortname, c=cache_timestamp())
        srcset.append(f'{url} {resolution}x')
    return ', '.join(srcset)


@jinjia.app_template_filter('music')
def contains_music(book_formats):
    result = False
    for format in book_formats:
        if format.format.lower() in g.constants.EXTENSIONS_AUDIO:
            result = True
    return result


@jinjia.app_template_filter('get_s3_cover_url')
def get_s3_cover_url(book, resolution='og'):
    """Get direct S3 URL for book cover if S3 is enabled and cover exists"""
    import os
    from . import ub
    
    # Map resolution to S3 path suffix
    s3_resolution = None if resolution == 'og' else resolution
    
    # Check if cover exists in S3 database
    try:
        upload_record = ub.session.query(ub.S3CoverUpload) \
            .filter(ub.S3CoverUpload.book_id == book.id) \
            .filter(ub.S3CoverUpload.resolution == s3_resolution) \
            .first()
        
        if upload_record:
            # Build S3 URL with hardcoded values
            bucket = os.environ.get('S3_BUCKET', 'cdn.mnd.vn')
            region = os.environ.get('S3_REGION', 'ap-southeast-1')
            
            cdn_url = os.environ.get('S3_CDN_URL', '')
            if cdn_url:
                return f"{cdn_url}/{upload_record.s3_key}"
            else:
                # Direct S3 URL format
                return f"https://s3.{region}.amazonaws.com/{bucket}/{upload_record.s3_key}"
    except Exception as e:
        log.debug("Error getting S3 URL: %s", e)
    
    return None
