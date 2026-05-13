import json
import random
import re
import time
import urllib
import uuid

import requests
requests.packages.urllib3.disable_warnings()
from bs4 import BeautifulSoup
from protobuf_to_dict import protobuf_to_dict

import static.Response_pb2 as ResponseProto
from builder.header import HeaderBuilder, HeaderType
from builder.params import Params
from builder.proto import ProtoBuilder
from utils.dy_util import splice_url, generate_a_bogus, generate_msToken, trans_cookies



class DouyinAPI:
    douyin_url = 'https://www.douyin.com'
    live_url = 'https://live.douyin.com'
    creator = "https://creator.douyin.com"

    @staticmethod
    def _fetch_webid_for_live(live_url: str) -> str:
        """
        Fetch visitor webid via mcs endpoint (used by live web requests).
        """
        api = "https://mcs.zijieapi.com/webid?aid=6383&sdk_version=5.1.24_dy"
        ua = HeaderBuilder.ua
        headers = {
            "user-agent": ua,
            "accept": "*/*",
            "content-type": "application/json;charset=UTF-8",
            "origin": "https://live.douyin.com",
            "referer": live_url,
        }
        payload = {
            "app_id": 6383,
            "url": live_url,
            "referer": live_url,
            "user_agent": ua,
            "user_unique_id": "",
        }
        try:
            res = requests.post(api, data=json.dumps(payload), headers=headers, verify=False, timeout=10)
            data = res.json()
            if data.get("e") == 0 and data.get("web_id"):
                return str(data["web_id"])
        except Exception:
            pass
        return ""


    @staticmethod
    def get_user_all_work_info(auth, user_url: str, **kwargs) -> list:
        """
        鑾峰彇鐢ㄦ埛鍏ㄩ儴浣滃搧淇℃伅.
        :param auth: DouyinAuth object.
        :param user_url: 鐢ㄦ埛涓婚〉URL.
        :return: 鍏ㄩ儴浣滃搧淇℃伅.
        """
        max_cursor = "0"
        work_list = []
        while True:
            res_json = DouyinAPI.get_user_work_info(auth, user_url, max_cursor)
            if "aweme_list" not in res_json.keys():
                break
            works = res_json["aweme_list"]
            max_cursor = str(res_json["max_cursor"])
            work_list.extend(works)
            if res_json["has_more"] != 1:
                break
        return work_list


    @staticmethod
    def get_user_work_info(auth, user_url: str, max_cursor, **kwargs) -> dict:
        """
        鑾峰彇鐢ㄦ埛浣滃搧淇℃伅.
        :param auth: DouyinAuth object.
        :param user_url:  鐢ㄦ埛涓婚〉URL.
        :param max_cursor:  涓婁竴娆¤姹傜殑max_cursor.
        :return:
        """
        api = f"/aweme/v1/web/aweme/post/"
        user_id = user_url.split("/")[-1].split("?")[0]
        headers = HeaderBuilder().build(HeaderType.GET)
        headers.set_referer(user_url)
        params = Params()
        params.add_param("device_platform", 'webapp')
        params.add_param("aid", '6383')
        params.add_param("channel", 'channel_pc_web')
        params.add_param("sec_user_id", user_id)
        params.add_param("max_cursor", max_cursor)
        params.add_param("locate_query", 'false')
        params.add_param("show_live_replay_strategy", '1')
        params.add_param("need_time_list", '1' if max_cursor == '0' else '0')
        params.add_param("time_list_query", '0')
        params.add_param("whale_cut_token", '')
        params.add_param("cut_version", '1')
        params.add_param("count", '18')
        params.add_param("publish_video_strategy_type", '2')
        params.add_param("update_version_code", '170400')
        params.add_param("pc_client_type", '1')
        params.add_param("version_code", '290100')
        params.add_param("version_name", '29.1.0')
        params.add_param("cookie_enabled", 'true')
        params.add_param("screen_width", '1707')
        params.add_param("screen_height", '960')
        params.add_param("browser_language", 'zh-CN')
        params.add_param("browser_platform", 'Win32')
        params.add_param("browser_name", 'Edge')
        params.add_param("browser_version", '125.0.0.0')
        params.add_param("browser_online", 'true')
        params.add_param("engine_name", 'Blink')
        params.add_param("engine_version", '125.0.0.0')
        params.add_param("os_name", 'Windows')
        params.add_param("os_version", '10')
        params.add_param("cpu_core_num", '32')
        params.add_param("device_memory", '8')
        params.add_param("platform", 'PC')
        params.add_param("downlink", '10')
        params.add_param("effective_type", '4g')
        params.add_param("round_trip_time", '100')
        params.with_web_id(auth, user_url)
        params.add_param("verifyFp", auth.cookie['s_v_web_id'])
        params.add_param("fp", auth.cookie['s_v_web_id'])
        params.add_param("msToken",
                         auth.msToken)
        params.with_a_bogus()
        resp = requests.get(f'{DouyinAPI.douyin_url}{api}', headers=headers.get(), cookies=auth.cookie,
                            params=params.get(), verify=False)
        return json.loads(resp.text)

    @staticmethod
    def get_work_info(auth, url: str) -> dict:
        """
        鑾峰彇浣滃搧淇℃伅.
        :param auth: DouyinAuth object.
        :param url: 浣滃搧URL.
        :return: JSON.
        """
        api = f"/aweme/v1/web/aweme/detail/"
        if 'video' in url:
            aweme_id = url.split("/")[-1].split("?")[0]
        else:
            aweme_id = re.findall(r'modal_id=(\d+)', url)[0]
            url = f'https://www.douyin.com/video/{aweme_id}'
        headers = HeaderBuilder().build(HeaderType.GET)
        headers.set_referer(url)
        params = Params()
        params.add_param("device_platform", "webapp")
        params.add_param("aid", "6383")
        params.add_param("channel", "channel_pc_web")
        params.add_param("aweme_id", aweme_id)
        params.add_param("update_version_code", "170400")
        params.add_param("pc_client_type", "1")
        params.add_param("version_code", "190500")
        params.add_param("version_name", "19.5.0")
        params.add_param("cookie_enabled", "true")
        params.add_param("screen_width", "1707")
        params.add_param("screen_height", "960")
        params.add_param("browser_language", "zh-CN")
        params.add_param("browser_platform", "Win32")
        params.add_param("browser_name", "Edge")
        params.add_param("browser_version", "125.0.0.0")
        params.add_param("browser_online", "true")
        params.add_param("engine_name", "Blink")
        params.add_param("engine_version", "125.0.0.0")
        params.add_param("os_name", "Windows")
        params.add_param("os_version", "10")
        params.add_param("cpu_core_num", "32")
        params.add_param("device_memory", "8")
        params.add_param("platform", "PC")
        params.add_param("downlink", "4.75")
        params.add_param("effective_type", "4g")
        params.add_param("round_trip_time", "150")
        params.with_web_id(auth, url)
        params.add_param("msToken", auth.msToken)
        params.with_a_bogus()
        params.add_param("verifyFp", auth.cookie['s_v_web_id'])
        params.add_param("fp", auth.cookie['s_v_web_id'])
        resp = requests.get(f'{DouyinAPI.douyin_url}{api}', headers=headers.get(), cookies=auth.cookie,
                            params=params.get(), verify=False)
        resp_json = json.loads(resp.text)
        return resp_json

    @staticmethod
    def get_work_out_comment(auth, url: str, cursor: str = '0', **kwargs) -> dict:
        """
        鑾峰彇浣滃搧鐨勫叏閮ㄤ竴绾ц瘎璁?
        :param auth: DouyinAuth object.
        :param url: 浣滃搧URL.
        :param cursor: 璇勮娓告爣.
        :return: JSON.
        """
        api = f"/aweme/v1/web/comment/list/"
        if 'video' in url:
            aweme_id = url.split("/")[-1].split("?")[0]
        else:
            aweme_id = re.findall(r'modal_id=(\d+)', url)[0]
            url = f'https://www.douyin.com/video/{aweme_id}'
        headers = HeaderBuilder().build(HeaderType.GET)
        headers.set_referer(url)
        params = Params()
        params.add_param("device_platform", "webapp")
        params.add_param("aid", "6383")
        params.add_param("channel", "channel_pc_web")
        params.add_param("aweme_id", aweme_id)
        params.add_param("cursor", cursor)
        params.add_param("count", "5")
        params.add_param("item_type", "0")
        params.add_param("whale_cut_token", "")
        params.add_param("cut_version", "1")
        params.add_param("rcFT", "")
        params.add_param("update_version_code", "170400")
        params.add_param("pc_client_type", "1")
        params.add_param("version_code", "170400")
        params.add_param("version_name", "17.4.0")
        params.add_param("cookie_enabled", "true")
        params.add_param("screen_width", "1707")
        params.add_param("screen_height", "960")
        params.add_param("browser_language", "zh-CN")
        params.add_param("browser_platform", "Win32")
        params.add_param("browser_name", "Edge")
        params.add_param("browser_version", "125.0.0.0")
        params.add_param("browser_online", "true")
        params.add_param("engine_name", "Blink")
        params.add_param("engine_version", "125.0.0.0")
        params.add_param("os_name", "Windows")
        params.add_param("os_version", "10")
        params.add_param("cpu_core_num", "32")
        params.add_param("device_memory", "8")
        params.add_param("platform", "PC")
        params.add_param("downlink", "10")
        params.add_param("effective_type", "4g")
        params.add_param("round_trip_time", "0")
        params.with_web_id(auth, url)
        params.add_param("verifyFp", auth.cookie['s_v_web_id'])
        params.add_param("fp", auth.cookie['s_v_web_id'])
        params.add_param("msToken", auth.msToken)
        params.with_a_bogus()
        resp = requests.get(f'{DouyinAPI.douyin_url}{api}', headers=headers.get(), cookies=auth.cookie,
                            params=params.get(), verify=False)
        resp_json = json.loads(resp.text)
        return resp_json

    @staticmethod
    def get_work_all_out_comment(auth, url: str, **kwargs) -> list:
        """
        鑾峰彇浣滃搧鍏ㄩ儴涓€绾ц瘎璁?
        :param auth: DouyinAuth object.
        :param url: 浣滃搧URL.
        :return:
        """
        cursor = "0"
        comment_list = []
        while True:
            res_json = DouyinAPI.get_work_out_comment(auth, url, cursor)
            comments = res_json["comments"]
            cursor = str(res_json["cursor"])
            if comments is None or len(comments) == 0:
                break
            comment_list.extend(comments)
            if res_json["has_more"] != 1:
                break
        return comment_list

    @staticmethod
    def get_work_inner_comment(auth, comment: dict, cursor: str, count: str = '3', **kwargs):
        """
        鑾峰彇浣滃搧璇勮鐨勪簩绾ц瘎璁?
        :param count: 瑕佽幏鍙栫殑浜岀骇璇勮鏁伴噺.
        :param auth: DouyinAuth object.
        :param comment: 涓€绾ц瘎璁轰俊鎭?
        :param cursor: 璇勮娓告爣.
        :return:
        """
        api = f"/aweme/v1/web/comment/list/reply/"
        aweme_id = comment['aweme_id']
        comment_id = comment['cid']
        headers = HeaderBuilder().build(HeaderType.GET)
        refer = f'https://www.douyin.com/video/{aweme_id}'
        headers.set_referer(refer)
        params = Params()
        params.add_param("device_platform", "webapp")
        params.add_param("aid", "6383")
        params.add_param("channel", "channel_pc_web")
        params.add_param("item_id", aweme_id)
        params.add_param("comment_id", comment_id)
        params.add_param("cut_version", "1")
        params.add_param("cursor", cursor)
        params.add_param("count", count)
        params.add_param("item_type", "0")
        params.add_param("update_version_code", "170400")
        params.add_param("pc_client_type", "1")
        params.add_param("version_code", "170400")
        params.add_param("version_name", "17.4.0")
        params.add_param("cookie_enabled", "true")
        params.add_param("screen_width", "1707")
        params.add_param("screen_height", "960")
        params.add_param("browser_language", "zh-CN")
        params.add_param("browser_platform", "Win32")
        params.add_param("browser_name", "Edge")
        params.add_param("browser_version", "125.0.0.0")
        params.add_param("browser_online", "true")
        params.add_param("engine_name", "Blink")
        params.add_param("engine_version", "125.0.0.0")
        params.add_param("os_name", "Windows")
        params.add_param("os_version", "10")
        params.add_param("cpu_core_num", "32")
        params.add_param("device_memory", "8")
        params.add_param("platform", "PC")
        params.add_param("downlink", "10")
        params.add_param("effective_type", "4g")
        params.add_param("round_trip_time", "0")
        params.with_web_id(auth, refer)
        params.add_param("verifyFp", auth.cookie['s_v_web_id'])
        params.add_param("fp", auth.cookie['s_v_web_id'])
        params.add_param("msToken", auth.msToken)
        params.with_a_bogus()
        resp = requests.get(f'{DouyinAPI.douyin_url}{api}', headers=headers.get(), cookies=auth.cookie,
                            params=params.get(), verify=False)
        resp_json = json.loads(resp.text)
        return resp_json

    @staticmethod
    def get_work_all_inner_comment(auth, comment: dict, **kwargs) -> list:
        """
        鑾峰彇浣滃搧璇勮鐨勫叏閮ㄤ簩绾ц瘎璁?
        :param auth: DouyinAuth object.
        :param comment: 涓€绾ц瘎璁轰俊鎭?
        :return: 浜岀骇璇勮鍒楄〃.
        """
        cursor = "0"
        count = '5'
        comment_list = []
        while True:
            res_json = DouyinAPI.get_work_inner_comment(auth, comment, cursor, count)
            comments = res_json["comments"]
            cursor = str(res_json["cursor"])
            if type(comments) is list and len(comments) > 0:
                comment_list.extend(comments)
            if res_json["has_more"] != 1:
                break
        return comment_list

    @staticmethod
    def get_work_all_comment(auth, url: str, **kwargs):
        """
        鑾峰彇浣滃搧鍏ㄩ儴璇勮.
        :param auth: DouyinAuth object.
        :param url: 浣滃搧URL.
        :return: 鍏ㄩ儴璇勮鍒楄〃.
        """
        out_comment_list = DouyinAPI.get_work_all_out_comment(auth, url)
        for comment in out_comment_list:
            comment['reply_comment'] = []
            if comment['reply_comment_total'] > 0:
                inner_comment_list = DouyinAPI.get_work_all_inner_comment(auth, comment)
                comment['reply_comment'] = inner_comment_list
        return out_comment_list

    @staticmethod
    def get_user_info(auth, user_url: str, **kwargs) -> dict:
        """
        鑾峰彇鐢ㄦ埛淇℃伅.
        :param auth: DouyinAuth object.
        :param user_url: 鐢ㄦ埛涓婚〉URL.
        :return: 鐢ㄦ埛淇℃伅.
        """
        api = f"/aweme/v1/web/user/profile/other/"
        user_id = user_url.split("/")[-1].split("?")[0]
        headers = HeaderBuilder().build(HeaderType.GET)
        headers.set_referer(user_url)
        params = Params()
        params.add_param("device_platform", 'webapp')
        params.add_param("aid", '6383')
        params.add_param("channel", 'channel_pc_web')
        params.add_param("publish_video_strategy_type", '2')
        params.add_param("source", 'channel_pc_web')
        params.add_param("sec_user_id", user_id)
        params.add_param("personal_center_strategy", '1')
        params.add_param("update_version_code", '170400')
        params.add_param("pc_client_type", '1')
        params.add_param("version_code", '170400')
        params.add_param("version_name", '17.4.0')
        params.add_param("cookie_enabled", 'true')
        params.add_param("screen_width", '1707')
        params.add_param("screen_height", '960')
        params.add_param("browser_language", 'zh-CN')
        params.add_param("browser_platform", 'Win32')
        params.add_param("browser_name", 'Edge')
        params.add_param("browser_version", '125.0.0.0')
        params.add_param("browser_online", 'true')
        params.add_param("engine_name", 'Blink')
        params.add_param("engine_version", '125.0.0.0')
        params.add_param("os_name", 'Windows')
        params.add_param("os_version", '10')
        params.add_param("cpu_core_num", '32')
        params.add_param("device_memory", '8')
        params.add_param("platform", 'PC')
        params.add_param("downlink", '10')
        params.add_param("effective_type", '4g')
        params.add_param("round_trip_time", '100')
        params.with_web_id(auth, user_url)
        params.add_param("msToken", auth.msToken)
        params.add_param('verifyFp', auth.cookie['s_v_web_id'])
        params.add_param('fp', auth.cookie['s_v_web_id'])
        params.with_a_bogus()
        resp = requests.get(f'{DouyinAPI.douyin_url}{api}', headers=headers.get(), cookies=auth.cookie,
                            params=params.get(), verify=False)
        return json.loads(resp.text)

    @staticmethod
    def search_general_work(auth, query: str, sort_type: str = '0', publish_time: str = '0', offset: str = '0',
                            filter_duration="", search_range="", content_type="", **kwargs):
        """
        鎼滅储缁煎悎棰戦亾浣滃搧.
        :param auth: DouyinAuth object.
        :param query: 鎼滅储鍏抽敭瀛?
        :param sort_type: 鎺掑簭鏂瑰紡 0 缁煎悎鎺掑簭, 1 鏈€澶氱偣璧? 2 鏈€鏂板彂甯?
        :param publish_time: 鍙戝竷鏃堕棿 0 涓嶉檺, 1 涓€澶╁唴, 7 涓€鍛ㄥ唴, 180 鍗婂勾鍐?
        :param offset: 鎼滅储缁撴灉鍋忕Щ閲?
        :param filter_duration: 瑙嗛鏃堕暱 绌哄瓧绗︿覆 涓嶉檺, 0-1 涓€鍒嗛挓鍐? 1-5 1-5鍒嗛挓鍐? 5-10000 5鍒嗛挓浠ヤ笂
        :param search_range: 鎼滅储鑼冨洿 0 涓嶉檺, 1 鏈€杩戠湅杩? 2 杩樻湭鐪嬭繃, 3 鍏虫敞鐨勪汉
        :param content_type: 鍐呭褰㈠紡 0 涓嶉檺, 1 瑙嗛, 2 鍥炬枃
        :return: JSON鏁版嵁.
        """
        api = f"/aweme/v1/web/general/search/single/"
        headers = HeaderBuilder().build(HeaderType.GET)
        refer = f'https://www.douyin.com/search/{urllib.parse.quote(query)}?aid={uuid.uuid4()}&type=general'
        headers.set_referer(refer)
        params = Params()
        params.add_param("device_platform", "webapp")
        params.add_param("aid", "6383")
        params.add_param("channel", "channel_pc_web")
        params.add_param("search_channel", "aweme_general")
        params.add_param("enable_history", "1")
        params.add_param("filter_selected", r'{"sort_type":"%s","publish_time":"%s","filter_duration":"%s",'
                                            r'"search_range":"%s","content_type":"%s"}' % (sort_type, publish_time,
                                                                                           filter_duration,
                                                                                           search_range, content_type))
        params.add_param("keyword", query)
        params.add_param("search_source", "tab_search")
        params.add_param("query_correct_type", "1")
        params.add_param("is_filter_search", "1")
        params.add_param("from_group_id", "")
        params.add_param("offset", offset)
        params.add_param("count", '25')
        params.add_param("need_filter_settings", '1' if offset == '0' else '0')
        params.add_param("list_type", "single")
        params.add_param("update_version_code", "170400")
        params.add_param("pc_client_type", "1")
        params.add_param("version_code", "190600")
        params.add_param("version_name", "19.6.0")
        params.add_param("cookie_enabled", "true")
        params.add_param("screen_width", "1707")
        params.add_param("screen_height", "960")
        params.add_param("browser_language", "zh-CN")
        params.add_param("browser_platform", "Win32")
        params.add_param("browser_name", "Edge")
        params.add_param("browser_version", "125.0.0.0")
        params.add_param("browser_online", "true")
        params.add_param("engine_name", "Blink")
        params.add_param("engine_version", "125.0.0.0")
        params.add_param("os_name", "Windows")
        params.add_param("os_version", "10")
        params.add_param("cpu_core_num", "32")
        params.add_param("device_memory", "8")
        params.add_param("platform", "PC")
        params.add_param("downlink", "10")
        params.add_param("effective_type", "4g")
        params.add_param("round_trip_time", "50")
        params.with_web_id(auth, refer)
        params.add_param("msToken", auth.msToken)
        params.with_a_bogus()
        resp = requests.get(f'{DouyinAPI.douyin_url}{api}', headers=headers.get(), cookies=auth.cookie,
                            params=params.get(), verify=False)
        return json.loads(resp.text)

    @staticmethod
    def search_some_general_work(auth, query: str, num: int, sort_type: str, publish_time: str, filter_duration="", search_range="", content_type="", **kwargs) -> list:
        """
        鎼滅储鎸囧畾鏁伴噺缁煎悎棰戦亾浣滃搧.
        :param auth: DouyinAuth object.
        :param query: 鎼滅储鍏抽敭瀛?
        :param num: 鎼滅储缁撴灉鏁伴噺.
        :param sort_type: 鎺掑簭鏂瑰紡 0 缁煎悎鎺掑簭, 1 鏈€澶氱偣璧? 2 鏈€鏂板彂甯?
        :param publish_time: 鍙戝竷鏃堕棿 0 涓嶉檺, 1 涓€澶╁唴, 7 涓€鍛ㄥ唴, 180 鍗婂勾鍐?
        :param filter_duration: 瑙嗛鏃堕暱 绌哄瓧绗︿覆 涓嶉檺, 0-1 涓€鍒嗛挓鍐? 1-5 1-5鍒嗛挓鍐? 5-10000 5鍒嗛挓浠ヤ笂
        :param search_range: 鎼滅储鑼冨洿 0 涓嶉檺, 1 鏈€杩戠湅杩? 2 杩樻湭鐪嬭繃, 3 鍏虫敞鐨勪汉
        :param content_type: 鍐呭褰㈠紡 0 涓嶉檺, 1 瑙嗛, 2 鍥炬枃
        :return: 浣滃搧鍒楄〃.
        """
        offset = "0"
        work_list = []
        while True:
            res_json = DouyinAPI.search_general_work(auth, query, sort_type, publish_time, offset,
                                                     filter_duration, search_range, content_type)
            works = res_json["data"]
            work_list.extend(works)
            if res_json["has_more"] != 1 or len(work_list) >= num:
                break
            offset = str(int(offset) + len(works))
        if len(work_list) > num:
            work_list = work_list[:num]
        return work_list

    @staticmethod
    def search_some_user(auth, query: str, num: int, **kwargs) -> list:
        """
        鎼滅储鎸囧畾鏁伴噺鐢ㄦ埛.
        :param auth: DouyinAuth object.
        :param query: 鎼滅储鍏抽敭瀛?
        :param num: 鎼滅储缁撴灉鏁伴噺.
        :return: 鐢ㄦ埛鍒楄〃.
        """
        offset = "0"
        count = "25"
        user_list = []
        while True:
            res_json = DouyinAPI.search_user(auth, query, offset, count)
            users = res_json["user_list"]
            user_list.extend(users)
            if res_json["has_more"] != 1 or len(user_list) >= num:
                break
            offset = str(int(offset) + int(count))
        if len(user_list) > num:
            user_list = user_list[:num]
        return user_list


    @staticmethod
    def search_user(auth, query: str, offset: str = '0', num: str = '25', douyin_user_fans="", douyin_user_type="", **kwargs):
        """
        鎼滅储鐢ㄦ埛.
        :param auth: DouyinAuth object.
        :param query:  鎼滅储鍏抽敭瀛?
        :param offset:  鎼滅储缁撴灉鍋忕Щ閲?
        :param num:  鎼滅储缁撴灉鏁伴噺.
        :param douyin_user_fans: 绮変笣鏁伴噺 绌哄瓧绗︿覆 (0_1k 1000浠ヤ笅) (1k_1w 1000-10000) (1w_10w 10000-100000) (10w_100w 10w-100w绮変笣) (100w_ 100w浠ヤ笂)
        :param douyin_user_type: 鐢ㄦ埛绫诲瀷 绌哄瓧绗︿覆 涓嶉檺 common_user 鏅€氱敤鎴?enterprise_user 浼佷笟鐢ㄦ埛 personal_user 涓汉璁よ瘉鐢ㄦ埛
        :return: JSON鏁版嵁.
        """
        api = "/aweme/v1/web/discover/search"
        headers = HeaderBuilder().build(HeaderType.GET)
        refer = f'https://www.douyin.com/search/{urllib.parse.quote(query)}?aid={uuid.uuid4()}&type=general'
        headers.set_referer(refer)
        params = Params()
        params.add_param("device_platform", 'webapp')
        params.add_param("aid", '6383')
        params.add_param("channel", 'channel_pc_web')
        params.add_param("search_channel", 'aweme_user_web')
        params.add_param("search_filter_value", r'{"douyin_user_fans":["%s"],"douyin_user_type":["%s"]}' % (
            douyin_user_fans, douyin_user_type))
        params.add_param("keyword", query)
        params.add_param("search_source", 'switch_tab')
        params.add_param("query_correct_type", '1')
        params.add_param("is_filter_search", '1')
        # params.add_param("from_group_id", '7378456704385600820')
        params.add_param("offset", offset)
        params.add_param("count", num)
        params.add_param("need_filter_settings", '1' if offset == '0' else '0')
        params.add_param("list_type", 'single')
        params.add_param("update_version_code", '170400')
        params.add_param("pc_client_type", '1')
        params.add_param("version_code", '170400')
        params.add_param("version_name", '17.4.0')
        params.add_param("cookie_enabled", 'true')
        params.add_param("screen_width", '1707')
        params.add_param("screen_height", '960')
        params.add_param("browser_language", 'zh-CN')
        params.add_param("browser_platform", 'Win32')
        params.add_param("browser_name", 'Edge')
        params.add_param("browser_version", '125.0.0.0')
        params.add_param("browser_online", 'true')
        params.add_param("engine_name", 'Blink')
        params.add_param("engine_version", '125.0.0.0')
        params.add_param("os_name", 'Windows')
        params.add_param("os_version", '10')
        params.add_param("cpu_core_num", '32')
        params.add_param("device_memory", '8')
        params.add_param("platform", 'PC')
        params.add_param("downlink", '10')
        params.add_param("effective_type", '4g')
        params.add_param("round_trip_time", '150')
        params.with_web_id(auth, refer)
        params.add_param("msToken", auth.msToken)
        params.with_a_bogus()
        resp = requests.get(f'{DouyinAPI.douyin_url}{api}', headers=headers.get(), cookies=auth.cookie,
                            params=params.get(), verify=False)
        return resp.json()

    @staticmethod
    def search_live(auth, query: str, offset: str = '0', num: str = '25', **kwargs):
        """
        鎼滅储鐩存挱.
        :param auth: DouyinAuth object.
        :param query:  鎼滅储鍏抽敭瀛?
        :param offset:  鎼滅储缁撴灉鍋忕Щ閲?
        :param num:  鎼滅储鏁伴噺.
        :return: JSON鏁版嵁.
        """
        api = "/aweme/v1/web/live/search/"
        headers = HeaderBuilder().build(HeaderType.GET)
        refer = f'https://www.douyin.com/search/{urllib.parse.quote(query)}?aid={uuid.uuid4()}&type=live'
        headers.set_referer(refer)
        params = Params()
        params.add_param("device_platform", 'webapp')
        params.add_param("aid", '6383')
        params.add_param("channel", 'channel_pc_web')
        params.add_param("search_channel", 'aweme_live')
        params.add_param("keyword", query)
        params.add_param("search_source", 'normal_search')
        params.add_param("query_correct_type", '1')
        params.add_param("is_filter_search", '0')
        params.add_param("from_group_id", '')
        params.add_param("offset", offset)
        params.add_param("count", num)
        params.add_param("need_filter_settings", '1' if offset == '0' else '0')
        params.add_param("list_type", 'single')
        params.add_param("update_version_code", '170400')
        params.add_param("pc_client_type", '1')
        params.add_param("version_code", '170400')
        params.add_param("version_name", '17.4.0')
        params.add_param("cookie_enabled", 'true')
        params.add_param("screen_width", '1707')
        params.add_param("screen_height", '960')
        params.add_param("browser_language", 'zh-CN')
        params.add_param("browser_platform", 'Win32')
        params.add_param("browser_name", 'Edge')
        params.add_param("browser_version", '125.0.0.0')
        params.add_param("browser_online", 'true')
        params.add_param("engine_name", 'Blink')
        params.add_param("engine_version", '125.0.0.0')
        params.add_param("os_name", 'Windows')
        params.add_param("os_version", '10')
        params.add_param("cpu_core_num", '32')
        params.add_param("device_memory", '8')
        params.add_param("platform", 'PC')
        params.add_param("downlink", '10')
        params.add_param("effective_type", '4g')
        params.add_param("round_trip_time", '50')
        params.with_web_id(auth, refer)
        params.add_param("msToken", auth.msToken)
        params.with_a_bogus()
        resp = requests.get(f'{DouyinAPI.douyin_url}{api}', headers=headers.get(), cookies=auth.cookie,
                            params=params.get(), verify=False)
        return resp.json()

    @staticmethod
    def search_some_live(auth, query: str, num: int, **kwargs) -> list:
        """
        鎼滅储鎸囧畾鏁伴噺鐩存挱.
        :param auth: DouyinAuth object.
        :param query:  鎼滅储鍏抽敭瀛?
        :param num:  鎼滅储鏁伴噺.
        :return: 鐩存挱鍒楄〃.
        """
        offset = "0"
        count = "25"
        live_list = []
        while True:
            res_json = DouyinAPI.search_live(auth, query, offset, count)
            lives = res_json["data"]
            live_list.extend(lives)
            if res_json["has_more"] != 1 or len(live_list) >= num:
                break
            offset = str(int(offset) + int(count))
        if len(live_list) > num:
            live_list = live_list[:num]
        return live_list

    @staticmethod
    def get_user_favorite(auth, sec_id: str, max_cursor: str = '0', num: str = '18', **kwargs):
        """
        鑾峰彇鐢ㄦ埛鏀惰棌.
        :param auth: DouyinAuth object.
        :param sec_id:  鐢ㄦ埛SECID.
        :param max_cursor:  缈婚〉娓告爣.
        :param num: 瑕佽幏鍙栫殑鏀惰棌鏁伴噺.
        :return: JSON.
        """
        headers = HeaderBuilder.build(HeaderType.GET)
        refer = f"https://www.douyin.com/user/{sec_id}?showTab=like"
        headers.set_referer(refer)
        params = Params()
        params.add_param("device_platform", 'webapp')
        params.add_param("aid", '6383')
        params.add_param("channel", 'channel_pc_web')
        params.add_param("sec_user_id", 'MS4wLjABAAAA99bTJ_GOw3odYmsXOe7i7xuEv0iQf2X_Kg_VUyVP0U8')
        params.add_param("max_cursor", max_cursor)
        params.add_param("min_cursor", '0')
        params.add_param("whale_cut_token", '')
        params.add_param("cut_version", '1')
        params.add_param("count", num)
        params.add_param("publish_video_strategy_type", '2')
        params.add_param("update_version_code", '170400')
        params.add_param("pc_client_type", '1')
        params.add_param("version_code", '170400')
        params.add_param("version_name", '17.4.0')
        params.add_param("cookie_enabled", 'true')
        params.add_param("screen_width", '1707')
        params.add_param("screen_height", '960')
        params.add_param("browser_language", 'zh-CN')
        params.add_param("browser_platform", 'Win32')
        params.add_param("browser_name", 'Edge')
        params.add_param("browser_version", '125.0.0.0')
        params.add_param("browser_online", 'true')
        params.add_param("engine_name", 'Blink')
        params.add_param("engine_version", '125.0.0.0')
        params.add_param("os_name", 'Windows')
        params.add_param("os_version", '10')
        params.add_param("cpu_core_num", '32')
        params.add_param("device_memory", '8')
        params.add_param("platform", 'PC')
        params.add_param("downlink", '10')
        params.add_param("effective_type", '4g')
        params.add_param("round_trip_time", '100')
        params.with_web_id(auth=auth, url=refer)
        params.add_param("verifyFp", auth.cookie['s_v_web_id'])
        params.add_param("fp", auth.cookie['s_v_web_id'])
        params.add_param("msToken",
                         auth.msToken)
        params.with_a_bogus()
        response = requests.get('https://www.douyin.com/aweme/v1/web/aweme/favorite/', params=params.get(),
                                headers=headers.get(), cookies=auth.cookie,
                                verify=False)
        return response.json()


    @staticmethod
    def get_my_uid(auth, **kwargs) -> int:
        """
        鑾峰彇鑷繁鐨勭敤鎴稩D.
        :param auth: DouyinAuth object.
        :return: 鐢ㄦ埛ID.
        """
        url = 'https://www.douyin.com/aweme/v1/web/query/user/'
        headers = HeaderBuilder().build(HeaderType.GET)
        refer = 'https://www.douyin.com/'
        headers.set_header('referer', refer)
        params = Params()
        params.with_platform()
        params.with_web_id(auth, refer)
        params.with_ms_token()
        params.add_param('verifyFp', auth.cookie['s_v_web_id'])
        params.add_param('fp', auth.cookie['s_v_web_id'])
        params.with_a_bogus()
        resp = requests.get(url, params=params.get(), verify=False, headers=headers.get(), cookies=auth.cookie)
        resp_json = json.loads(resp.text)
        return int(resp_json['user_uid'])

    @staticmethod
    def get_my_sec_uid(auth, **kwargs) -> str:
        """
        鑾峰彇鑷繁鐨凷ECID.
        :param auth: DouyinAuth object.
        :return: SECID.
        """
        headers = HeaderBuilder().build(HeaderType.GET)
        url = "https://www.douyin.com/user/self"
        params = {
            "from_tab_name": "main"
        }
        response = requests.get(url, headers=headers.get(), cookies=auth.cookie, params=params)
        sec_uid = re.findall(r'\\"secUid\\":\\"(.*?)\\"', response.text)[0]
        return sec_uid


    @staticmethod
    def get_live_info(auth_, live_id, **kwargs):
        """
        鑾峰彇鐩存挱闂翠俊鎭?
        :param live_id: 鐩存挱闂碔D
        :return: 鐩存挱闂碔D, 鐢ㄦ埛ID, ttwid
        """
        url = "https://live.douyin.com/" + live_id
        headers = HeaderBuilder().build(HeaderType.GET)
        # Avoid occasional brotli decode errors in some Python environments.
        headers.set_header("accept-encoding", "gzip, deflate")
        headers.set_referer(url)

        # 1) Primary path: use live enter API (more stable than parsing HTML).
        api_url = "https://live.douyin.com/webcast/room/web/enter/"
        api_params = {
            "aid": "6383",
            "device_platform": "web",
            "language": "zh-CN",
            "cookie_enabled": "true",
            "screen_width": "1920",
            "screen_height": "1080",
            "browser_language": "zh-CN",
            "browser_platform": "Win32",
            "browser_name": "Chrome",
            "browser_version": "124.0.0.0",
            "browser_online": "true",
            "engine_name": "Blink",
            "engine_version": "124.0.0.0",
            "os_name": "Windows",
            "os_version": "10",
            "cpu_core_num": "12",
            "device_memory": "8",
            "platform": "PC",
            "downlink": "10",
            "effective_type": "4g",
            "round_trip_time": "50",
            "web_rid": str(live_id),
        }
        api_res = requests.get(
            api_url,
            params=api_params,
            headers=headers.get(),
            cookies=auth_.cookie,
            verify=False,
        )

        ttwid = (
            api_res.cookies.get_dict().get("ttwid")
            or auth_.cookie.get("ttwid")
        )
        if not ttwid:
            raise RuntimeError("Unable to get ttwid from response or provided cookie.")

        ws_user_unique_id = DouyinAPI._fetch_webid_for_live(url)
        try:
            payload = api_res.json()
            rooms = payload.get("data", {}).get("data", [])
            if rooms:
                room = rooms[0]
                owner = room.get("owner") or {}
                room_id = room.get("id_str")
                user_id = owner.get("id_str") or room.get("owner_user_id_str")
                if room_id and user_id:
                    return {
                        "room_id": str(room_id),
                        "user_id": str(user_id),
                        "ws_user_unique_id": str(ws_user_unique_id or user_id),
                        "ttwid": ttwid,
                        "room_status": str(room.get("status", "")),
                        "room_title": room.get("title", ""),
                    }
        except Exception:
            pass

        # 2) Fallback path: parse legacy room info from HTML.
        res = requests.get(url, headers=headers.get(), cookies=auth_.cookie, verify=False)
        soup = BeautifulSoup(res.text, 'html.parser')
        scripts = soup.select('script[nonce]')
        for script in scripts:
            if script.string is not None and 'roomId' in script.string:
                try:
                    room_id = re.findall(r'\\"roomId\\":\\"(\d+)\\"', script.string)[0]
                    user_id = re.findall(r'\\"user_unique_id\\":\\"(\d+)\\"', script.string)[0]
                    room_info = re.findall(r'\\"roomInfo\\":\{\\"room\\":\{\\"id_str\\":\\".*?\\",\\"status\\":(.*?),\\"status_str\\":\\".*?\\",\\"title\\":\\"(.*?)\\"', script.string)[0]
                    room_status = room_info[0]
                    room_title = room_info[1]
                    return {
                        "room_id": room_id,
                        "user_id": user_id,
                        "ws_user_unique_id": str(ws_user_unique_id or user_id),
                        "ttwid": ttwid,
                        "room_status": room_status,
                        "room_title": room_title
                    }
                except Exception:
                    continue
        raise RuntimeError(f"Unable to parse live room info from API and page: {url}")

    @staticmethod
    def get_live_production(auth, url: str, room_id: str, author_id: str, offset: str, **kwargs):
        """
        鑾峰彇鐩存挱闂寸殑鍟嗗搧淇℃伅.
        :param auth: DouyinAuth object.
        :param url: 鐩存挱闂撮摼鎺?
        :param room_id: 鐩存挱闂碔D
        :param author_id: 涓绘挱ID
        :param offset: 缈婚〉娓告爣.
        :return: JSON 鍟嗗搧鍒楄〃.
        """
        api = f"/live/promotions/page/"
        headers = HeaderBuilder().build(HeaderType.GET)
        headers.set_header("origin", DouyinAPI.live_url)
        headers.set_referer(url)
        params = Params()
        params.add_param("device_platform", "webapp")
        params.add_param("aid", "6383")
        params.add_param("channel", "channel_pc_web")
        params.add_param("room_id", room_id)
        params.add_param("author_id", author_id)
        params.add_param("offset", offset)
        params.add_param("limit", "20")
        params.add_param("pc_client_type", "1")
        params.add_param("version_code", "210800")
        params.add_param("version_name", "21.8.0")
        params.add_param("cookie_enabled", "true")
        params.add_param("screen_width", "2560")
        params.add_param("screen_height", "1440")
        params.add_param("browser_language", "zh-CN")
        params.add_param("browser_platform", "Win32")
        params.add_param("browser_name", "Edge")
        params.add_param("browser_version", "121.0.0.0")
        params.add_param("browser_online", "true")
        params.add_param("engine_name", "Blink")
        params.add_param("engine_version", "121.0.0.0")
        params.add_param("os_name", "Windows")
        params.add_param("os_version", "10")
        params.add_param("cpu_core_num", "20")
        params.add_param("device_memory", "8")
        params.add_param("platform", "PC")
        params.add_param("downlink", "10")
        params.add_param("effective_type", "4g")
        params.add_param("round_trip_time", "50")
        params.with_web_id(auth, url)
        params.add_param("msToken", auth.msToken)
        params.with_a_bogus()
        res = requests.post(f'{DouyinAPI.live_url}{api}', headers=headers.get(), cookies=auth.cookie,
                           params=params.get(), verify=False)
        return res.json()

    @staticmethod
    def get_all_live_production(auth, url: str, **kwargs):
        """
        鑾峰彇鐩存挱闂寸殑鎵€鏈夊晢鍝佷俊鎭?
        :param auth: DouyinAuth object.
        :param url: 鐩存挱闂撮摼鎺?
        :return:
        """
        room_info = DouyinAPI.get_live_info(auth, url.split("/")[-1].split("?")[0])
        room_id = room_info["room_id"]
        author_id = room_info["author_id"]
        offset = "0"
        production_list = []
        while True:
            res_json = DouyinAPI.get_live_production(auth, url, room_id, author_id, offset)
            productions = res_json["promotions"]
            production_list.extend(productions)
            offset = str(res_json["next_offset"])
            if offset == "-1":
                break
        return production_list

    @staticmethod
    def get_live_production_detail(auth, url, ec_promotion_id, sec_author_id, live_room_id, **kwargs):
        """
        鑾峰彇鐩存挱闂村晢鍝佽鎯?
        :param auth: DouyinAuth object.
        :param url: 鐩存挱闂撮摼鎺?
        :param ec_promotion_id: 鍟嗗搧ID.
        :param sec_author_id: 涓绘挱ID
        :param live_room_id: 鐩存挱闂碔D
        :return: JSON 鍟嗗搧璇︽儏.
        """
        api = f"/ecom/product/detail/saas/pc/"
        headers = HeaderBuilder().build(HeaderType.FORM)
        headers.set_header("origin", DouyinAPI.live_url)
        headers.set_referer(url)
        headers.with_csrf(auth.cookie_str)
        params = Params()
        params.add_param("is_h5", "1")
        params.add_param("origin_type", "638301")
        params.add_param("device_platform", "webapp")
        params.add_param("aid", "6383")
        params.add_param("channel", "channel_pc_web")
        params.add_param("pc_client_type", "1")
        params.add_param("update_version_code", "170400")
        params.add_param("version_code", "")
        params.add_param("version_name", "")
        params.add_param("cookie_enabled", "true")
        params.add_param("screen_width", "1707")
        params.add_param("screen_height", "960")
        params.add_param("browser_language", "zh-CN")
        params.add_param("browser_platform", "Win32")
        params.add_param("browser_name", "Edge")
        params.add_param("browser_version", "125.0.0.0")
        params.add_param("browser_online", "true")
        params.add_param("engine_name", "Blink")
        params.add_param("engine_version", "125.0.0.0")
        params.add_param("os_name", "Windows")
        params.add_param("os_version", "10")
        params.add_param("cpu_core_num", "32")
        params.add_param("device_memory", "8")
        params.add_param("platform", "PC")
        params.add_param("downlink", "1.7")
        params.add_param("effective_type", "4g")
        params.add_param("round_trip_time", "200")
        params.with_web_id(auth, url)
        params.add_param("msToken", auth.msToken)
        data = {
            "bff_type": "2",
            "ec_promotion_id": ec_promotion_id,
            "is_h5": "1",
            "item_id": "0",
            "live_room_id": live_room_id,
            "origin_type": "638301",
            "promotion_ids": ec_promotion_id,
            "room_id": live_room_id,
            "sec_author_id": sec_author_id,
            "use_new_price": "1"
        }
        params.with_a_bogus(data)
        res = requests.post(f'{DouyinAPI.live_url}{api}', headers=headers.get(), params=params.get(),
                            cookies=auth.cookie, data=data, verify=False)
        return res.json()

    @staticmethod
    def collect_aweme(auth, aweme_id: str, action: str = '1', **kwargs):
        """
        鏀惰棌鎴栧彇娑堟敹钘忚棰?
        :param auth: DouyinAuth object.
        :param aweme_id: 瑙嗛ID.
        :param action: 1: 鏀惰棌, 0: 鍙栨秷鏀惰棌.
        :return: 鍝嶅簲JSON.
        """
        api = '/aweme/v1/web/aweme/collect/'
        headers = HeaderBuilder().build(HeaderType.FORM)
        refer = "https://www.douyin.com/?recommend=1"
        headers.set_referer(refer)
        headers.with_bd(api, auth)
        headers.with_csrf(auth.cookie_str)
        headers.set_header("origin", DouyinAPI.douyin_url)
        params = Params()
        params.add_param("device_platform", "webapp")
        params.add_param("aid", "6383")
        params.add_param("channel", "channel_pc_web")
        params.add_param("pc_client_type", "1")
        params.add_param("update_version_code", "170400")
        params.add_param("version_code", "170400")
        params.add_param("version_name", "17.4.0")
        params.add_param("cookie_enabled", "true")
        params.add_param("screen_width", "1707")
        params.add_param("screen_height", "960")
        params.add_param("browser_language", "zh-CN")
        params.add_param("browser_platform", "Win32")
        params.add_param("browser_name", "Edge")
        params.add_param("browser_version", "125.0.0.0")
        params.add_param("browser_online", "true")
        params.add_param("engine_name", "Blink")
        params.add_param("engine_version", "125.0.0.0")
        params.add_param("os_name", "Windows")
        params.add_param("os_version", "10")
        params.add_param("cpu_core_num", "32")
        params.add_param("device_memory", "8")
        params.add_param("platform", "PC")
        params.add_param("downlink", "10")
        params.add_param("effective_type", "4g")
        params.add_param("round_trip_time", "50")
        params.with_web_id(auth, refer)
        params.add_param("verifyFp", auth.cookie['s_v_web_id'])
        params.add_param("fp", auth.cookie['s_v_web_id'])
        params.add_param("msToken", auth.msToken)
        data = {
            "action": action,
            "aweme_id": aweme_id,
            "aweme_type": "0",
        }
        params.with_a_bogus(data)
        res = requests.post(f'{DouyinAPI.douyin_url}{api}', headers=headers.get(), params=params.get(),
                            cookies=auth.cookie, data=data, verify=False)
        return res.json()

    @staticmethod
    def move_collect_aweme(auth, aweme_id: str, collect_name: str, collect_id: str, **kwargs):
        """
        绉诲姩瑙嗛鍒版寚瀹氭敹钘忓す锛堥渶瑕佸厛鏀惰棌瑙嗛锛?
        :param collect_name: 鏀惰棌澶瑰悕绉?
        :param collect_id: 鏀惰棌澶笽D
        :param auth: DouyinAuth object.
        :param aweme_id: 瑙嗛ID.
        :return: 鍝嶅簲JSON.
        """
        api = '/aweme/v1/web/collects/video/move/'
        headers = HeaderBuilder().build(HeaderType.FORM)
        refer = "https://www.douyin.com/?recommend=1"
        headers.set_referer(refer)
        headers.with_bd(api, auth)
        headers.with_csrf(auth.cookie_str)
        headers.set_header("origin", DouyinAPI.douyin_url)
        params = Params()
        params.add_param("aid", "6383")
        params.add_param("browser_language", "zh-CN")
        params.add_param("browser_name", "Edge")
        params.add_param("browser_online", "true")
        params.add_param("browser_platform", "Win32")
        params.add_param("browser_version", "125.0.0.0")
        params.add_param("channel", "channel_pc_web")
        params.add_param("collects_name", collect_name)
        params.add_param("cookie_enabled", "true")
        params.add_param("cpu_core_num", "32")
        params.add_param("device_memory", "8")
        params.add_param("device_platform", "webapp")
        params.add_param("downlink", "10")
        params.add_param("effective_type", "4g")
        params.add_param("engine_name", "Blink")
        params.add_param("engine_version", "125.0.0.0")
        params.add_param("item_ids", aweme_id)
        params.add_param("item_type", "2")
        params.add_param("move_collects_list", collect_id)
        params.add_param("os_name", "Windows")
        params.add_param("os_version", "10")
        params.add_param("pc_client_type", "1")
        params.add_param("platform", "PC")
        params.add_param("round_trip_time", "50")
        params.add_param("screen_height", "960")
        params.add_param("screen_width", "1707")
        params.add_param("to_collects_id", collect_id)
        params.add_param("update_collects_sort", "true")
        params.add_param("update_version_code", "170400")
        params.add_param("version_code", "170400")
        params.add_param("version_name", "17.4.0")
        params.with_web_id(auth, refer)
        params.add_param("verifyFp", auth.cookie['s_v_web_id'])
        params.add_param("fp", auth.cookie['s_v_web_id'])
        params.add_param("msToken", auth.msToken)
        params.with_a_bogus()
        res = requests.post(f'{DouyinAPI.douyin_url}{api}', headers=headers.get(), params=params.get(),
                            cookies=auth.cookie, verify=False)
        return res.json()

    @staticmethod
    def remove_collect_aweme(auth, aweme_id: str, collect_name: str, collect_id: str, **kwargs):
        """
        浠庢寚瀹氭敹钘忓す涓Щ闄よ棰戯紙闇€瑕佸厛鏀惰棌瑙嗛锛?
        :param collect_name: 鏀惰棌澶瑰悕绉?
        :param collect_id: 鏀惰棌澶笽D
        :param auth: DouyinAuth object.
        :param aweme_id: 瑙嗛ID.
        :return: 鍝嶅簲JSON.
        """
        api = '/aweme/v1/web/collects/video/move/'
        headers = HeaderBuilder().build(HeaderType.FORM)
        refer = "https://www.douyin.com/user/self?showTab=favorite_collection"
        headers.set_referer(refer)
        headers.with_bd(api, auth)
        headers.with_csrf(auth.cookie_str)
        headers.set_header("origin", DouyinAPI.douyin_url)
        params = Params()
        params.add_param("aid", "6383")
        params.add_param("browser_language", "zh-CN")
        params.add_param("browser_name", "Edge")
        params.add_param("browser_online", "true")
        params.add_param("browser_platform", "Win32")
        params.add_param("browser_version", "125.0.0.0")
        params.add_param("channel", "channel_pc_web")
        params.add_param("collects_name", collect_name)
        params.add_param("cookie_enabled", "true")
        params.add_param("cpu_core_num", "32")
        params.add_param("device_memory", "8")
        params.add_param("device_platform", "webapp")
        params.add_param("downlink", "10")
        params.add_param("effective_type", "4g")
        params.add_param("engine_name", "Blink")
        params.add_param("engine_version", "125.0.0.0")
        params.add_param("from_collects_id", collect_id)
        params.add_param("item_ids", aweme_id)
        params.add_param("item_type", "2")
        params.add_param("os_name", "Windows")
        params.add_param("os_version", "10")
        params.add_param("pc_client_type", "1")
        params.add_param("platform", "PC")
        params.add_param("round_trip_time", "50")
        params.add_param("screen_height", "960")
        params.add_param("screen_width", "1707")
        params.add_param("update_version_code", "170400")
        params.add_param("version_code", "170400")
        params.add_param("version_name", "17.4.0")
        params.with_web_id(auth, refer)
        params.add_param("verifyFp", auth.cookie['s_v_web_id'])
        params.add_param("fp", auth.cookie['s_v_web_id'])
        params.add_param("msToken", auth.msToken)
        params.with_a_bogus()
        res = requests.post(f'{DouyinAPI.douyin_url}{api}', headers=headers.get(), params=params.get(),
                            cookies=auth.cookie, verify=False)
        return res.json()

    @staticmethod
    def get_collect_list(auth, **kwargs):
        """
        鑾峰彇鎴戠殑鏀惰棌澶瑰垪琛?
        :param auth: DouyinAuth object.
        :return: JSON.
        """
        api = "/aweme/v1/web/collects/list/"
        headers = HeaderBuilder().build(HeaderType.GET)
        refer = "https://www.douyin.com/?recommend=1"
        headers.set_referer(refer)
        params = Params()
        params.add_param("device_platform", "webapp")
        params.add_param("aid", "6383")
        params.add_param("channel", "channel_pc_web")
        params.add_param("cursor", "0")
        params.add_param("count", "20")
        params.add_param("update_version_code", "170400")
        params.add_param("pc_client_type", "1")
        params.add_param("version_code", "170400")
        params.add_param("version_name", "17.4.0")
        params.add_param("cookie_enabled", "true")
        params.add_param("screen_width", "1707")
        params.add_param("screen_height", "960")
        params.add_param("browser_language", "zh-CN")
        params.add_param("browser_platform", "Win32")
        params.add_param("browser_name", "Edge")
        params.add_param("browser_version", "125.0.0.0")
        params.add_param("browser_online", "true")
        params.add_param("engine_name", "Blink")
        params.add_param("engine_version", "125.0.0.0")
        params.add_param("os_name", "Windows")
        params.add_param("os_version", "10")
        params.add_param("cpu_core_num", "32")
        params.add_param("device_memory", "8")
        params.add_param("platform", "PC")
        params.add_param("downlink", "5.95")
        params.add_param("effective_type", "4g")
        params.add_param("round_trip_time", "200")
        params.with_web_id(auth, refer)
        params.add_param("msToken", auth.msToken)
        params.with_a_bogus()
        params.add_param("verifyFp", auth.cookie['s_v_web_id'])
        params.add_param("fp", auth.cookie['s_v_web_id'])
        res = requests.get(f'{DouyinAPI.douyin_url}{api}', headers=headers.get(), params=params.get(),
                           cookies=auth.cookie, verify=False)
        return res.json()

    @staticmethod
    def get_user_follower_list(auth, user_id: str, sec_id: str, max_time: str = '0', count: str = '20', **kwargs):
        """
        鑾峰彇鐢ㄦ埛鐨勭矇涓濆垪琛?
        :param auth: DouyinAuth object.
        :param user_id: 鐢ㄦ埛ID.
        :param sec_id: 鐢ㄦ埛sec_id.
        :param max_time: 鏈€澶ф椂闂存埑.
        :param count: 鏁伴噺.
        :return:  JSON.
        """
        api = "/aweme/v1/web/user/follower/list/"
        headers = HeaderBuilder().build(HeaderType.GET)
        refer = f"https://www.douyin.com/user/{sec_id}"
        headers.set_referer(refer)
        params = Params()
        params.add_param("device_platform", 'webapp')
        params.add_param("aid", '6383')
        params.add_param("channel", 'channel_pc_web')
        params.add_param("user_id", user_id)
        params.add_param("sec_user_id", sec_id)
        params.add_param("offset", '0')
        params.add_param("min_time", '0')
        params.add_param("max_time", max_time)
        params.add_param("count", count)
        params.add_param("source_type", '2' if max_time == '0' else '1')
        params.add_param("gps_access", '0')
        params.add_param("address_book_access", '0')
        params.add_param("update_version_code", '170400')
        params.add_param("pc_client_type", '1')
        params.add_param("version_code", '170400')
        params.add_param("version_name", '17.4.0')
        params.add_param("cookie_enabled", 'true')
        params.add_param("screen_width", '1707')
        params.add_param("screen_height", '960')
        params.add_param("browser_language", 'zh-CN')
        params.add_param("browser_platform", 'Win32')
        params.add_param("browser_name", 'Edge')
        params.add_param("browser_version", '125.0.0.0')
        params.add_param("browser_online", 'true')
        params.add_param("engine_name", 'Blink')
        params.add_param("engine_version", '125.0.0.0')
        params.add_param("os_name", 'Windows')
        params.add_param("os_version", '10')
        params.add_param("cpu_core_num", '32')
        params.add_param("device_memory", '8')
        params.add_param("platform", 'PC')
        params.add_param("downlink", '10')
        params.add_param("effective_type", '4g')
        params.add_param("round_trip_time", '150')
        params.with_web_id(auth, refer)
        params.add_param("msToken", auth.msToken)
        params.with_a_bogus()
        params.add_param("verifyFp", auth.cookie['s_v_web_id'])
        params.add_param("fp", auth.cookie['s_v_web_id'])
        res = requests.get(f'{DouyinAPI.douyin_url}{api}', headers=headers.get(), params=params.get(),
                           cookies=auth.cookie, verify=False)
        return res.json()

    @staticmethod
    def get_some_user_follower_list(auth, user_id: str, sec_id: str, num: int, **kwargs) -> list:
        """
        鑾峰彇鐢ㄦ埛鐨勫墠num涓矇涓濆垪琛?
        :param auth: DouyinAuth object.
        :param user_id: 鐢ㄦ埛ID.
        :param sec_id: 鐢ㄦ埛sec_id.
        :param num: 瑕佽幏鍙栫殑鏁伴噺
        :return: 绮変笣鍒楄〃.
        """
        max_time = "0"
        count = "20"
        follower_list = []
        while True:
            res_json = DouyinAPI.get_user_follower_list(auth, user_id, sec_id, max_time, count)
            followers = res_json["followers"]
            follower_list.extend(followers)
            if res_json["has_more"] != 1 or len(follower_list) >= num:
                break
            max_time = res_json["min_time"]
        if len(follower_list) > num:
            follower_list = follower_list[:num]
        return follower_list

    @staticmethod
    def get_user_following_list(auth, user_id: str, sec_id: str, max_time: str = '0', count: str = '20', **kwargs):
        """
        鑾峰彇鐢ㄦ埛鐨勫叧娉ㄥ垪琛?
        :param auth: DouyinAuth object.
        :param user_id: 鐢ㄦ埛ID.
        :param sec_id: 鐢ㄦ埛sec_id.
        :param max_time: 鏈€澶ф椂闂存埑.
        :param count: 鏁伴噺.
        :return:
        """
        api = "/aweme/v1/web/user/following/list/"
        headers = HeaderBuilder().build(HeaderType.GET)
        refer = f"https://www.douyin.com/user/{sec_id}"
        headers.set_referer(refer)
        params = Params()
        params.add_param("device_platform", 'webapp')
        params.add_param("aid", '6383')
        params.add_param("channel", 'channel_pc_web')
        params.add_param("user_id", user_id)
        params.add_param("sec_user_id", sec_id)
        params.add_param("offset", '0')
        params.add_param("min_time", '0')
        params.add_param("max_time", max_time)
        params.add_param("count", count)
        params.add_param("source_type", '2' if max_time == '0' else '1')
        params.add_param("gps_access", '0')
        params.add_param("address_book_access", '0')
        params.add_param("is_top", '1')
        params.add_param("update_version_code", '170400')
        params.add_param("pc_client_type", '1')
        params.add_param("version_code", '170400')
        params.add_param("version_name", '17.4.0')
        params.add_param("cookie_enabled", 'true')
        params.add_param("screen_width", '1707')
        params.add_param("screen_height", '960')
        params.add_param("browser_language", 'zh-CN')
        params.add_param("browser_platform", 'Win32')
        params.add_param("browser_name", 'Edge')
        params.add_param("browser_version", '125.0.0.0')
        params.add_param("browser_online", 'true')
        params.add_param("engine_name", 'Blink')
        params.add_param("engine_version", '125.0.0.0')
        params.add_param("os_name", 'Windows')
        params.add_param("os_version", '10')
        params.add_param("cpu_core_num", '32')
        params.add_param("device_memory", '8')
        params.add_param("platform", 'PC')
        params.add_param("downlink", '10')
        params.add_param("effective_type", '4g')
        params.add_param("round_trip_time", '150')
        params.with_web_id(auth, refer)
        params.add_param("msToken", auth.msToken)
        params.with_a_bogus()
        params.add_param("verifyFp", auth.cookie['s_v_web_id'])
        params.add_param("fp", auth.cookie['s_v_web_id'])
        res = requests.get(f'{DouyinAPI.douyin_url}{api}', headers=headers.get(), params=params.get(),
                           cookies=auth.cookie, verify=False)
        return res.json()

    @staticmethod
    def get_some_user_following_list(auth, user_id: str, sec_id: str, num: int, **kwargs) -> list:
        """
        鑾峰彇鐢ㄦ埛鐨勫墠num涓叧娉ㄥ垪琛?
        :param auth: DouyinAuth object.
        :param user_id: 鐢ㄦ埛ID.
        :param sec_id: 鐢ㄦ埛sec_id.
        :param num: 瑕佽幏鍙栫殑鏁伴噺
        :return: 鍏虫敞鍒楄〃.
        """
        max_time = "0"
        count = "20"
        following_list = []
        while True:
            res_json = DouyinAPI.get_user_following_list(auth, user_id, sec_id, max_time, count)
            followings = res_json["followings"]
            following_list.extend(followings)
            if res_json["has_more"] != 1 or len(following_list) >= num:
                break
            max_time = res_json["min_time"]
        if len(following_list) > num:
            following_list = following_list[:num]
        return following_list

    @staticmethod
    def get_notice_list(auth, min_time='0', max_time='0', count='10', notice_group='700', **kwargs):
        """
        鑾峰緱閫氱煡
        :param auth: DouyinAuth object.
        :param min_time: 鏈€灏忔椂闂存埑.
        :param max_time: 鏈€澶ф椂闂存埑.
        :param count: 鏁伴噺.
        :param notice_group: 娑堟伅绫诲瀷 700 鍏ㄩ儴娑堟伅 401 绮変笣 601 @鎴戠殑 2 璇勮 3 鐐硅禐 520 寮瑰箷
        :return: JSON.
        """
        api = "/aweme/v1/web/notice/"
        headers = HeaderBuilder().build(HeaderType.GET)
        refer = "https://www.douyin.com/?recommend=1"
        headers.set_referer(refer)
        params = Params()
        params.add_param("device_platform", 'webapp')
        params.add_param("aid", '6383')
        params.add_param("channel", 'channel_pc_web')
        params.add_param("is_new_notice", '1')
        params.add_param("is_mark_read", '1')
        params.add_param("notice_group", notice_group)
        params.add_param("count", count)
        params.add_param("min_time", min_time)
        params.add_param("max_time", max_time)
        params.add_param("update_version_code", '170400')
        params.add_param("pc_client_type", '1')
        params.add_param("version_code", '170400')
        params.add_param("version_name", '17.4.0')
        params.add_param("cookie_enabled", 'true')
        params.add_param("screen_width", '1707')
        params.add_param("screen_height", '960')
        params.add_param("browser_language", 'zh-CN')
        params.add_param("browser_platform", 'Win32')
        params.add_param("browser_name", 'Edge')
        params.add_param("browser_version", '125.0.0.0')
        params.add_param("browser_online", 'true')
        params.add_param("engine_name", 'Blink')
        params.add_param("engine_version", '125.0.0.0')
        params.add_param("os_name", 'Windows')
        params.add_param("os_version", '10')
        params.add_param("cpu_core_num", '32')
        params.add_param("device_memory", '8')
        params.add_param("platform", 'PC')
        params.add_param("downlink", '10')
        params.add_param("effective_type", '4g')
        params.add_param("round_trip_time", '50')
        params.with_web_id(auth, refer)
        params.add_param("msToken", auth.msToken)
        params.with_a_bogus()
        params.add_param("verifyFp", auth.cookie['s_v_web_id'])
        params.add_param("fp", auth.cookie['s_v_web_id'])
        res = requests.get(f'{DouyinAPI.douyin_url}{api}', headers=headers.get(), params=params.get(),
                           cookies=auth.cookie, verify=False)
        return res.json()

    @staticmethod
    def get_some_notice_list(auth, num: int = 20, notice_group='700', **kwargs) -> list:
        """
        鑾峰緱鍓峮um鏉￠€氱煡
        :param auth: DouyinAuth object.
        :param num: 鏁伴噺.
        :param notice_group: 娑堟伅绫诲瀷 | 700 鍏ㄩ儴娑堟伅 401 绮変笣 601 @鎴戠殑 2 璇勮 3 鐐硅禐 520 寮瑰箷
        :return:
        """
        min_time = "0"
        max_time = "0"
        count = "10"
        notice_list = []
        while True:
            res_json = DouyinAPI.get_notice_list(auth, min_time, max_time, count, notice_group)
            notices = res_json["notice_list_v2"]
            notice_list.extend(notices)
            if res_json["has_more"] != 1 or len(notice_list) >= num:
                break
            min_time = res_json["min_time"]
            max_time = res_json["max_time"]
        if len(notice_list) > num:
            notice_list = notice_list[:num]
        return notice_list

    @staticmethod
    def get_feed(auth, count='20', refresh_index='2', **kwargs):
        """
        鑾峰彇棣栭〉鎺ㄨ崘瑙嗛
        :param auth: DouyinAuth object.
        :param count: 鏁伴噺.
        :param refresh_index: 鍒锋柊绱㈠紩.
        :return: JSON.
        """
        api = "/aweme/v1/web/module/feed/"
        headers = HeaderBuilder().build(HeaderType.GET)
        refer = "https://www.douyin.com/"
        headers.set_referer(refer)
        params = Params()
        params.add_param("device_platform", 'webapp')
        params.add_param("aid", '6383')
        params.add_param("channel", 'channel_pc_web')
        params.add_param("module_id", '3003101')
        params.add_param("count", count)
        params.add_param("filterGids", '')
        params.add_param("presented_ids", '')
        params.add_param("refresh_index", refresh_index)
        params.add_param("refer_id", '')
        params.add_param("refer_type", '10')
        params.add_param("awemePcRecRawData", '{"is_client":false}')
        params.add_param("Seo-Flag", '0')
        params.add_param("install_time", '1715480185')
        params.add_param("pc_client_type", '1')
        params.add_param("update_version_code", '170400')
        params.add_param("version_code", '170400')
        params.add_param("version_name", '17.4.0')
        params.add_param("cookie_enabled", 'true')
        params.add_param("screen_width", '1707')
        params.add_param("screen_height", '960')
        params.add_param("browser_language", 'zh-CN')
        params.add_param("browser_platform", 'Win32')
        params.add_param("browser_name", 'Edge')
        params.add_param("browser_version", '125.0.0.0')
        params.add_param("browser_online", 'true')
        params.add_param("engine_name", 'Blink')
        params.add_param("engine_version", '125.0.0.0')
        params.add_param("os_name", 'Windows')
        params.add_param("os_version", '10')
        params.add_param("cpu_core_num", '32')
        params.add_param("device_memory", '8')
        params.add_param("platform", 'PC')
        params.add_param("downlink", '10')
        params.add_param("effective_type", '4g')
        params.add_param("round_trip_time", '100')
        params.with_web_id(auth, refer)
        params.add_param("msToken", auth.msToken)
        params.with_a_bogus()
        params.add_param("verifyFp", auth.cookie['s_v_web_id'])
        params.add_param("fp", auth.cookie['s_v_web_id'])

        res = requests.get(f'{DouyinAPI.douyin_url}{api}', headers=headers.get(), params=params.get(),
                           cookies=auth.cookie, verify=False)
        return res.json()



