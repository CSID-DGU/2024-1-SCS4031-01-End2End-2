import json
import os
import re
import subprocess
import time

from bson import errors
from bson.objectid import ObjectId
from pymongo import ReturnDocument
from ppadb.client import Client as AdbClient


from com.dtmilano.android.viewclient import ViewClient
from flask import request, jsonify, make_response, g
import xml.etree.ElementTree as elemTree
import openai
from openai import OpenAI

from server.adb_util import ui_compare, ui_compare_fail, serial_no, device, execute_function, take_screenshot, \
    error_response, test_recommand_route, infer_viewid
from server.fine_tuning import init_train_data

from server import adb_function
from server import app
from server.s3_upload import s3_put_object

#Parse XML
tree = elemTree.parse('keys.xml')

openai.api_key = os.environ.get('OPENAI_API_KEY')
AWS_ACCESS_KEY = tree.find('string[@name="AWS_ACCESS_KEY"]').text
AWS_SECRET_KEY = tree.find('string[@name="AWS_SECRET_KEY"]').text
BUCKET_NAME = tree.find('string[@name="BUCKET_NAME"]').text
location = 'ap-northeast-2'

client = openai.OpenAI(api_key=openai.api_key)

# # 시리얼 번호
# device = device


# 시나리오 리스트 조회
def scenarios():
    if request.method == 'GET':
        scenario_list = app.config['scenario']
        cursor = scenario_list.find({}, {'scenario_name': 1, 'run_status': 1})

        # 쿼리 결과를 JSON 직렬화 가능한 형태로 변환
        scenarios = []
        for doc in cursor:
            # ObjectId를 문자열로 변환
            doc['_id'] = str(doc['_id']) if '_id' in doc else None
            scenarios.append(doc)

        return jsonify(list(scenarios))

# 시나리오 상세 보기
def scenario(scenario_id):
    if request.method == 'GET':
        scenario_list = app.config['scenario']

        try:
            # MongoDB에서 시나리오 문서를 조회()
            scenario_doc = scenario_list.find_one({'_id': ObjectId(scenario_id)})

        # 잘못된 scenario_id를 전달받은 경우 예외처리가 안됨
        except errors.InvalidId:
            return jsonify({'error': 'Invalid scenario ID format'}), 400

        if scenario_doc:
            scenario_doc['_id'] = str(scenario_doc['_id'])
            return jsonify(scenario_doc)
        else:
            return jsonify({'error': 'Scenario not found'}), 404

# 시나리오 생성
def create_scenario():
    if request.method == 'POST':
        scenario_list = app.config['scenario']
        template_list = app.config['template']

        scenario_name = request.json['scenario_name']
        template_id = request.json.get('template_id')  # 옵셔널로 가져오기

        if template_id:
            # 템플릿 조회
            template_doc = template_list.find_one({'_id': ObjectId(template_id)})

            if template_doc:
                template_data = template_doc.get('template', [])

                scenario_document = {
                    'scenario_name': scenario_name,
                    'run_status': 'ready',
                    'scenario': template_data
                }

                # 시나리오 컬렉션에 삽입
                scenario_list.insert_one(scenario_document)
        else:
            scenario_document = {'scenario_name': scenario_name,
                                 'run_status': 'ready',
                                 'scenario': [{'ui_data': "", 'screenshot_url': "", 'status': "ready"},
                                              {'action': "", 'status': "ready"},
                                              {'ui_data': "", 'screenshot_url': "", 'status': "ready"}]
                                 }

            inserted_data = scenario_list.insert_one(scenario_document)

        return jsonify({'message': 'Success'})

# 시나리오 작업 추가
def add_task():
    if request.method == 'POST':
        scenario_list = app.config['scenario']
        object_id = request.json['object_id']

        try:
            # MongoDB에서 시나리오 문서를 조회
            scenario_doc = scenario_list.find_one({'_id': ObjectId(object_id)})
        except errors.InvalidId:
            return jsonify({'error': 'Invalid scenario ID format'}), 400

        if scenario_doc:
            # 시나리오 문서에 작업 추가
            new_tasks = [{'action': "", 'status': "ready"},{'ui_data': "", 'screenshot_url': "", 'status': "ready"}]
            updated_scenario = scenario_list.find_one_and_update(
                {'_id': ObjectId(object_id)},
                {'$push': {'scenario': {'$each': new_tasks}}},
                return_document=ReturnDocument.AFTER
            )

            if updated_scenario:
                return jsonify({'message': 'success'})
            else:
                return jsonify({'error': 'Update failed'}), 500
        else:
            return jsonify({'error': 'Scenario not found'}), 404

def transform(ui_list, ui_data):
    for ui in ui_list:
        pattern_line_separator = '\n'
        ui = re.sub(pattern_line_separator, " ", ui)

        # 정규식을 사용하여 문자열을 분리합니다.
        pattern = r'(.+?) id/no_id/(\d+)'
        match = re.match(pattern, ui)

        component = match.group(1).strip()  # 앞뒤 공백 제거
        unique_id = match.group(2)

        ui_data[unique_id] = component
    # print(ui_data)

# 현재 계층 정보 추출 및 DB에 저장
def extracted_hierarchy(scenario_id):
    # global serial_no

    scenario_list = app.config['scenario']

    if request.method == 'POST':
        print("extracted_hierarchy")

        object_id = scenario_id
        index = int(request.json['index'])

        vc = ViewClient(*ViewClient.connectToDeviceOrExit(serialno=serial_no))
        # traverse_to_list 메서드를 사용하여 디바이스의 UI 계층 구조를 리스트로 반환(ViewClient로 부터 재 정의함)
        ui_list = vc.traverse_to_list(transform=vc.traverseShowClassIdTextAndUniqueId)  # vc의 디바이스 UI 트리를 순회하여 리스트로 반환

        # 스크린샷을 찍어서 s3에 저장
        screenshot_dir = take_screenshot()
        screenshot_url = s3_put_object(screenshot_dir)

        # 로컬에서 이미지 삭제
        os.remove(screenshot_dir)

        ui_data = {}
        # mongodb에 저장
        transform(ui_list, ui_data)

        result = scenario_list.update_one(
            {'_id': ObjectId(object_id), f'scenario.{index}': {'$exists': True}},
            {'$set': {
                f'scenario.{index}': {
                    'ui_data': ui_data,  # UI 데이터
                    'screenshot_url': screenshot_url,  # 스크린샷 URL
                    'status': 'ready'  # 상태
                }
            }}
        )

        return jsonify({
            'screenshot_url': screenshot_url,
        })

# action 저장
def save_action(scenario_id):
    scenario_list = app.config['scenario']

    if request.method == 'POST':
        object_id = scenario_id
        index = int(request.json['index'])
        action = request.json['action']

        # MongoDB에서 특정 시나리오의 특정 인덱스에 action 데이터를 업데이트
        result = scenario_list.update_one(
            {'_id': ObjectId(object_id), f'scenario.{index}': {'$exists': True}},
            {'$set': {
                f'scenario.{index}.action': action,
                f'scenario.{index}.status': 'ready'
            }}
        )

    return jsonify({"message": "success"})

# 시나리오 실행
def run_scenario(scenario_id):

    client = AdbClient(host="127.0.0.1", port=5037)
    devices = client.devices()

    # 연결된 디바이스가 없는 경우
    if not devices:
        print("No devices found")
        return error_response()

    device = devices[0]
    serial_no = device.serial

    scenario_list = app.config['scenario']
    scenario = scenario_list.find_one({'_id': ObjectId(scenario_id)})

    before_hierarchy = None
    now_index = 0
    scenario_seq = scenario['scenario']  # 시나리오 순서 추출(화면-액션-화면-액션...)

    # 전체 status 로딩으로 처리
    scenario_list.update_one(
        {'_id': ObjectId(scenario_id)},
        {'$set': {'run_status': 'loading'}}
    )

    # 모든 태스크를 로딩으로 처리
    for i in range(len(scenario_seq)):
        scenario_list.update_one(
            {'_id': ObjectId(scenario_id)},
            {'$set': {f'scenario.{i}.status': 'ready'}}
        )

    try:
        start = scenario_seq[0]
        start_hierarchy = start['ui_data']
        start_status = start['status']
        before_hierarchy = start_hierarchy

        # loading 처리
        scenario_list.update_one(
            {'_id': ObjectId(scenario_id)},
            {'$set': {'scenario.0.status': 'loading'}}
        )

        # 현재 화면 추출 및 변환
        vc = ViewClient(*ViewClient.connectToDeviceOrExit(serialno=serial_no))
        ui_list = vc.traverse_to_list(transform=vc.traverseShowClassIdTextAndUniqueId)
        ui_data = {}
        transform(ui_list, ui_data)
        # 시작화면과 현재 화면이 같은지 비교(홈화면 기준으로 시간이 조금만 달라도 계층정보가 다르다고 판단함)
        if(ui_compare(ui_data, before_hierarchy)):
            # 시작은 성공
            scenario_list.update_one(
                {'_id': ObjectId(scenario_id)},
                {'$set': {'scenario.0.status': 'success'}}
            )

        else: # 다른화면인 경우
            ui_compare_fail(now_index, scenario_id, scenario_list, scenario_seq)
            while True:
                adb_function.back(None)
                result = subprocess.run(
                    ["adb", "shell", "dumpsys", "window", "windows", "|", "grep", "-E", "'mCurrentFocus|mFocusedApp'"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True
                )

                # 결과 파싱
                output = result.stdout.strip().split('\n')
                for line in output:
                    if 'mCurrentFocus' in line:
                        mCurrentFocus = line.split('=')[1].strip()
                        print(mCurrentFocus)

                if mCurrentFocus == 'Window{9e54403d0 u0 com.sec.android.app.launcher/com.sec.android.app.launcher.activities.LauncherActivity}':
                    break

            return error_response()
    except Exception as e:
        # 첫 화면에서 실패했다면 모든 태스크는 실패 처리
        ui_compare_fail(now_index, scenario_id, scenario_list, scenario_seq)
        while True:
            adb_function.back(None)
            result = subprocess.run(
                ["adb", "shell", "dumpsys", "window", "windows", "|", "grep", "-E", "'mCurrentFocus|mFocusedApp'"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )

            # 결과 파싱
            output = result.stdout.strip().split('\n')
            for line in output:
                if 'mCurrentFocus' in line:
                    mCurrentFocus = line.split('=')[1].strip()
                    print(mCurrentFocus)

            if mCurrentFocus == 'Window{9e54403d0 u0 com.sec.android.app.launcher/com.sec.android.app.launcher.activities.LauncherActivity}':
                break

        return error_response()
    result = None
    # 이후 태스크 실행 및 검증
    for index in range(1, len(scenario_seq)):
        # loading 처리
        scenario_list.update_one(
            {'_id': ObjectId(scenario_id)},
            {'$set': {f'scenario.{index}.status': 'loading'}}
        )

        # 액션 검증
        if index%2==1:
            try:
                action_cmd = scenario_seq[index]['action']
                # action_status = scenario_seq[i]['status']
                # 문제없이 액션 값을 받아오면 성공
                result = infer_viewid(before_hierarchy, action_cmd)

                scenario_list.update_one(
                    {'_id': ObjectId(scenario_id)},
                    {'$set': {f'scenario.{index}.status': 'success'}}
                )
            except:
                ui_compare_fail(index, scenario_id, scenario_list, scenario_seq)
                while True:
                    adb_function.back(None)
                    result = subprocess.run(
                        ["adb", "shell", "dumpsys", "window", "windows", "|", "grep", "-E",
                         "'mCurrentFocus|mFocusedApp'"],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True
                    )

                    # 결과 파싱
                    output = result.stdout.strip().split('\n')
                    for line in output:
                        if 'mCurrentFocus' in line:
                            mCurrentFocus = line.split('=')[1].strip()
                            print(mCurrentFocus)

                    if mCurrentFocus == 'Window{9e54403d0 u0 com.sec.android.app.launcher/com.sec.android.app.launcher.activities.LauncherActivity}':
                        break

                return error_response()

        # 화면 검증(여기서 부터 수정해야 함. abd function쪽 수정과 같이 하기)
        elif index%2==0:
            try:
                after_hierarchy = scenario_seq[index]['ui_data']

                # adb 함수 수행
                if len(result) == 2:
                    key, function_name = result
                    execute_function(function_name, key)  # 문자열로 함수 실행

                else:
                    key, text, function_name = result
                    execute_function(function_name, key, text)  # 문자열로 함수 실행

                # 새로운 화면에 대한 계층정보 추출 변환
                vc = ViewClient(*ViewClient.connectToDeviceOrExit())
                vc.dump(window='-1', sleep=1)  # 현재 화면을 강제로 새로 고침
                ui_list = vc.traverse_to_list(transform=vc.traverseShowClassIdTextAndUniqueId)

                time.sleep(2)

                ui = {}
                transform(ui_list, ui)
                before_hierarchy = after_hierarchy

                # 새로운 화면과 계층정보가 동일하면 성공
                # 시작화면과 현재 화면이 같은지 비교(홈화면 기준으로 시간이 조금만 달라도 계층정보가 다르다고 판단함)
                if (ui_compare(ui, after_hierarchy)):
                    scenario_list.update_one(
                        {'_id': ObjectId(scenario_id)},
                        {'$set': {f'scenario.{index}.status': 'success'}}
                    )

                else:
                    print(Exception)
                    ui_compare_fail(index, scenario_id, scenario_list, scenario_seq)
                    while True:
                        adb_function.back(None)
                        result = subprocess.run(
                            ["adb", "shell", "dumpsys", "window", "windows", "|", "grep", "-E",
                             "'mCurrentFocus|mFocusedApp'"],
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            text=True
                        )

                        # 결과 파싱
                        output = result.stdout.strip().split('\n')
                        for line in output:
                            if 'mCurrentFocus' in line:
                                mCurrentFocus = line.split('=')[1].strip()
                                print(mCurrentFocus)

                        if mCurrentFocus == 'Window{9e54403d0 u0 com.sec.android.app.launcher/com.sec.android.app.launcher.activities.LauncherActivity}':
                            break

                    return error_response()

            except Exception as e:
                print(e)
                ui_compare_fail(index, scenario_id, scenario_list, scenario_seq)
                while True:
                    adb_function.back(None)
                    result = subprocess.run(
                        ["adb", "shell", "dumpsys", "window", "windows", "|", "grep", "-E",
                         "'mCurrentFocus|mFocusedApp'"],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True
                    )

                    # 결과 파싱
                    output = result.stdout.strip().split('\n')
                    for line in output:
                        if 'mCurrentFocus' in line:
                            mCurrentFocus = line.split('=')[1].strip()
                            print(mCurrentFocus)

                    if mCurrentFocus == 'Window{9e54403d0 u0 com.sec.android.app.launcher/com.sec.android.app.launcher.activities.LauncherActivity}':
                        break

                return error_response()

    scenario_list.update_one(
        {'_id': ObjectId(scenario_id)},
        {'$set': {'run_status': 'success'}}
    )

    while True:
        adb_function.back(None)
        result = subprocess.run(
            ["adb", "shell", "dumpsys", "window", "windows", "|", "grep", "-E", "'mCurrentFocus|mFocusedApp'"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        # 결과 파싱
        output = result.stdout.strip().split('\n')
        for line in output:
            if 'mCurrentFocus' in line:
                mCurrentFocus = line.split('=')[1].strip()
                print(mCurrentFocus)

        if mCurrentFocus == 'Window{9e54403d0 u0 com.sec.android.app.launcher/com.sec.android.app.launcher.activities.LauncherActivity}':
            break

    return jsonify({'message': 'Success'})

# 전체 시나리오 실행
def run_all_scenario():
    scenario_list = app.config['scenario']
    report_list = app.config['report']
    report_name = request.json['report_name']
    # report_dict = {"report_name": report_name}
    report_dict = {
        "report_name": report_name,
        "fail_report": [],
        "create_at": time.strftime('%Y-%m-%d %H:%M:%S')
    }
    report = report_list.insert_one(report_dict)
    report_obj_id = report_dict["_id"]
    report_obj_id = str(report_obj_id)

    for scenario in scenario_list.find():
        scenario_id = str(scenario.get('_id'))
        response = run_scenario_report(scenario_id, report_obj_id)
        print(response.status_code)

        while True:
            adb_function.back(None)
            result = subprocess.run(
                ["adb", "shell", "dumpsys", "window", "windows", "|", "grep", "-E", "'mCurrentFocus|mFocusedApp'"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )

            # 결과 파싱
            output = result.stdout.strip().split('\n')
            for line in output:
                if 'mCurrentFocus' in line:
                    mCurrentFocus = line.split('=')[1].strip()
                    print(mCurrentFocus)

            if mCurrentFocus == 'Window{9e54403d0 u0 com.sec.android.app.launcher/com.sec.android.app.launcher.activities.LauncherActivity}':
                break

    # 시나리오 전체 조회하고, 요약 보고서 생성
    all_scenario = scenario_list.find()
    success_scenario_cnt = 0 # 성공한 시나리오 개수
    fail_scenario_cnt = 0 # 실패한 시나리오 개수
    running_scenario_cnt = 0 # 실행한 시나리오 개수

    for scenario in all_scenario:
        if scenario.get("run_status") == "success":
            success_scenario_cnt+=1
            running_scenario_cnt+=1
        elif scenario.get("run_status") == "fail":
            fail_scenario_cnt+=1
            running_scenario_cnt+=1
        elif scenario.get("run_status") == "loading":
            pass

    pass_fail_per = success_scenario_cnt / running_scenario_cnt # 성공/실패 비율
    success_all_per = success_scenario_cnt / running_scenario_cnt  # 성공률

    summary_result = {
        "success_scenario_cnt" : success_scenario_cnt,
        "fail_scenario_cnt" : fail_scenario_cnt,
        "running_scenario_cnt" : running_scenario_cnt,
        "pass_fail_per" : pass_fail_per,
        "success_all_per" : success_all_per
    }

    # 도큐멘트 조회
    document = report_list.find_one({'_id': ObjectId(report_obj_id)})

    # 찾은 document에 데이터 추가
    document.update(summary_result)
    # 컬렉션 업데이트
    report_list.update_one({"_id": ObjectId(report_obj_id)}, {"$set": document})


    return jsonify({'message': 'Success'})

def delete_scenario(scenario_id):
    scenario_list = app.config['scenario']
    scenario_list.delete_one({'_id': ObjectId(scenario_id)})

    return jsonify({'message': 'Success'})

def test():
    test_recommand_route()



# 시나리오 실행
def run_scenario_report(scenario_id, report_obj_id):

    client = AdbClient(host="127.0.0.1", port=5037)
    devices = client.devices()

    # 연결된 디바이스가 없는 경우
    if not devices:
        print("No devices found")
        return error_response()

    device = devices[0]
    serial_no = device.serial

    scenario_list = app.config['scenario']
    report_list = app.config['report']

    scenario = scenario_list.find_one({'_id': ObjectId(scenario_id)})
    report = report_list.find_one({'_id': ObjectId(report_obj_id)})

    before_hierarchy = None
    now_index = 0
    scenario_seq = scenario['scenario']  # 시나리오 순서 추출(화면-액션-화면-액션...)


    # 전체 status 로딩으로 처리
    scenario_list.update_one(
        {'_id': ObjectId(scenario_id)},
        {'$set': {'run_status': 'loading'}}
    )

    # 모든 태스크를 로딩으로 처리
    for i in range(len(scenario_seq)):
        scenario_list.update_one(
            {'_id': ObjectId(scenario_id)},
            {'$set': {f'scenario.{i}.status': 'ready'}}
        )

    try:
        start = scenario_seq[0]
        start_hierarchy = start['ui_data']
        start_status = start['status']
        before_hierarchy = start_hierarchy

        # loading 처리
        scenario_list.update_one(
            {'_id': ObjectId(scenario_id)},
            {'$set': {'scenario.0.status': 'loading'}}
        )

        # 현재 화면 추출 및 변환
        vc = ViewClient(*ViewClient.connectToDeviceOrExit(serialno=serial_no))
        ui_list = vc.traverse_to_list(transform=vc.traverseShowClassIdTextAndUniqueId)
        ui_data = {}
        transform(ui_list, ui_data)
        # 시작화면과 현재 화면이 같은지 비교(홈화면 기준으로 시간이 조금만 달라도 계층정보가 다르다고 판단함)
        if(ui_compare(ui_data, before_hierarchy)):
            # 시작은 성공
            scenario_list.update_one(
                {'_id': ObjectId(scenario_id)},
                {'$set': {'scenario.0.status': 'success'}}
            )

        else: # 다른화면인 경우
            ui_compare_fail(now_index, scenario_id, scenario_list, scenario_seq)
            return error_response()
    except Exception as e:
        # 첫 화면에서 실패했다면 모든 태스크는 실패 처리
        ui_compare_fail(now_index, scenario_id, scenario_list, scenario_seq)
        return error_response()
    result = None
    # 이후 태스크 실행 및 검증
    for index in range(1, len(scenario_seq)):
        # loading 처리
        scenario_list.update_one(
            {'_id': ObjectId(scenario_id)},
            {'$set': {f'scenario.{index}.status': 'loading'}}
        )

        # 액션 검증
        if index%2==1:
            try:
                action_cmd = scenario_seq[index]['action']
                # action_status = scenario_seq[i]['status']
                # 문제없이 액션 값을 받아오면 성공
                result = infer_viewid(before_hierarchy, action_cmd)

                scenario_list.update_one(
                    {'_id': ObjectId(scenario_id)},
                    {'$set': {f'scenario.{index}.status': 'success'}}
                )
            except:
                ui_compare_fail(index, scenario_id, scenario_list, scenario_seq)

                while True:
                    adb_function.back(None)
                    result = subprocess.run(
                        ["adb", "shell", "dumpsys", "window", "windows", "|", "grep", "-E",
                         "'mCurrentFocus|mFocusedApp'"],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True
                    )

                    # 결과 파싱
                    output = result.stdout.strip().split('\n')
                    for line in output:
                        if 'mCurrentFocus' in line:
                            mCurrentFocus = line.split('=')[1].strip()
                            print(mCurrentFocus)

                    if mCurrentFocus == 'Window{9e54403d0 u0 com.sec.android.app.launcher/com.sec.android.app.launcher.activities.LauncherActivity}':
                        break

                return error_response()

        # 화면 검증(여기서 부터 수정해야 함. abd function쪽 수정과 같이 하기)
        elif index%2==0:
            try:
                after_hierarchy = scenario_seq[index]['ui_data']

                # adb 함수 수행
                if len(result) == 2:
                    key, function_name = result
                    execute_function(function_name, key)  # 문자열로 함수 실행

                else:
                    key, text, function_name = result
                    execute_function(function_name, key, text)  # 문자열로 함수 실행

                # 새로운 화면에 대한 계층정보 추출 변환
                vc = ViewClient(*ViewClient.connectToDeviceOrExit())
                vc.dump(window='-1', sleep=1)  # 현재 화면을 강제로 새로 고침
                ui_list = vc.traverse_to_list(transform=vc.traverseShowClassIdTextAndUniqueId)

                ui = {}
                transform(ui_list, ui)

                # 새로운 화면과 계층정보가 동일하면 성공
                # 시작화면과 현재 화면이 같은지 비교(홈화면 기준으로 시간이 조금만 달라도 계층정보가 다르다고 판단함)
                if (ui_compare(ui, after_hierarchy)):
                    scenario_list.update_one(
                        {'_id': ObjectId(scenario_id)},
                        {'$set': {f'scenario.{index}.status': 'success'}}
                    )

                    before_hierarchy = after_hierarchy

                else:
                    print(Exception)
                    ui_compare_fail(index, scenario_id, scenario_list, scenario_seq) # 현재 인덱스

                    # 실제 시나리오와 다른 새로운 화면에 대해 스크린샷
                    screenshot_dir = take_screenshot()
                    screenshot_url = s3_put_object(screenshot_dir)

                    # index-2, index-1, index db에서 가져온거랑
                    existing_new_screen = scenario_seq[index] # 기존 new 화면
                    existing_action = scenario_seq[index-1] # 기존 action
                    existing_old_screen = scenario_seq[index-2] # 기존 old 화면

                    fail_report={
                        "scenario_name": scenario['scenario_name'],
                        "existing_old_screen": existing_old_screen["screenshot_url"],
                        "existing_action": existing_action["action"],
                        "existing_new_screen": existing_new_screen["screenshot_url"],
                        "fail_new_screen": screenshot_url
                    }

                    report_list.update_one(
                        {'_id': ObjectId(report_obj_id)},
                        {'$push': {'fail_report': fail_report}}
                    )

                    while True:
                        adb_function.back(None)
                        result = subprocess.run(
                            ["adb", "shell", "dumpsys", "window", "windows", "|", "grep", "-E",
                             "'mCurrentFocus|mFocusedApp'"],
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            text=True
                        )

                        # 결과 파싱
                        output = result.stdout.strip().split('\n')
                        for line in output:
                            if 'mCurrentFocus' in line:
                                mCurrentFocus = line.split('=')[1].strip()
                                print(mCurrentFocus)

                        if mCurrentFocus == 'Window{9e54403d0 u0 com.sec.android.app.launcher/com.sec.android.app.launcher.activities.LauncherActivity}':
                            break

                    return error_response()

            except Exception as e:
                print(e)
                ui_compare_fail(index, scenario_id, scenario_list, scenario_seq)

                while True:
                    adb_function.back(None)
                    result = subprocess.run(
                        ["adb", "shell", "dumpsys", "window", "windows", "|", "grep", "-E",
                         "'mCurrentFocus|mFocusedApp'"],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True
                    )

                    # 결과 파싱
                    output = result.stdout.strip().split('\n')
                    for line in output:
                        if 'mCurrentFocus' in line:
                            mCurrentFocus = line.split('=')[1].strip()
                            print(mCurrentFocus)

                    if mCurrentFocus == 'Window{9e54403d0 u0 com.sec.android.app.launcher/com.sec.android.app.launcher.activities.LauncherActivity}':
                        break

                return error_response()

    scenario_list.update_one(
        {'_id': ObjectId(scenario_id)},
        {'$set': {'run_status': 'success'}}
    )
    return jsonify({'message': 'Success'})