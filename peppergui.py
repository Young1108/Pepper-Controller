# -*- coding: utf-8 -*-
from motion_parser import MotionParser
import os
import pygubu
from PIL import Image, ImageTk
from pepper.robot import Pepper
import numpy as np
import yaml
import cv2
import threading
from hellopepper import basic_demo, take_picture_show, recognize_person, learn_person
import time
import threading
import sys
import subprocess
import random
import qi

PROJECT_PATH = os.path.abspath(os.path.dirname(__file__))
PROJECT_UI = os.path.join(PROJECT_PATH, "pepper_controller.ui")


class Configuration:

    def __init__(self, config_file=os.path.join(PROJECT_PATH,"conf.yaml")):
        self.config_file = config_file
        self.conf = yaml.safe_load(open(self.config_file))


class PepperControllerApp:
    def __init__(self, master=None):
        self.builder = builder = pygubu.Builder()
        builder.add_resource_path(PROJECT_PATH)
        builder.add_from_file(PROJECT_UI)
        self.mainwindow = builder.get_object('toplevel1', master)

        # pygubu variables
        self.move_speed = None
        self.text_to_say = None
        self.volume = None
        self.voice_pitch = None
        self.voice_speed = None
        self.ipaddress = None
        self.port = None
        self.chatbot_voice_stop = 500
        self.chatbot_voice_sens = 0.5
        self.chatbot_person_left = 7000
        self.load_standup_config()
        builder.import_variables(self, [u'move_speed', u'text_to_say',
                                        u'volume', u'voice_pitch', u'voice_speed', u'ipaddress', u'port'])

        builder.connect_callbacks(self)

        # robot properties
        self.configuration = Configuration()
        self.robot = None
        self.ip_address = None
        self.port = None
        self.language = self.configuration.conf["language"]["lang"]

        # default settings
        self.builder.tkvariables['ipaddress'].set(
            self.configuration.conf["configuration"]["default_ip"])
        self.builder.tkvariables['port'].set(
            self.configuration.conf["configuration"]["default_port"])
        self.builder.tkvariables['text_to_say'].set(
            self.configuration.conf["configuration"]["default_sentence"])

        # title
        top_level = self.builder.get_object('toplevel1')
        self.top_level = top_level
        top_level.title("Pepper Controller " +
                        self.configuration.conf["configuration"]["version"])

        # gesture names:
        i = 1
        while True:
            try:
                button = self.builder.get_object('gesture_' + str(i))
                name = self.configuration.conf["gesture_" + str(i)]["name"]
                button.config(text=name)
                i += 1
            except:
                break

        # app names
        i = 1
        while True:
            try:
                button = self.builder.get_object('application_' + str(i))
                name = self.configuration.conf["application_" + str(i)]["name"]
                button.config(text=name)
                i += 1
            except:
                break

        # video properties
        self.canvas = builder.get_object('canvas1')
        self.video_thread = threading.Thread(target=self.start_stream)
        self.thread_alive = False
        self.stream_on = -1  # -1 == initial, 0 == off, 1 == on

        # movement
        self.movement_state = "stop"

        self.motorics = self.builder.get_object('motorics')

        # close action
        top_level.protocol("WM_DELETE_WINDOW", self.on_closing)

        # pick camera settings
        self.builder.get_object('pick_camera').current(0)

        # workout settings
        self.arms_combobox = self.builder.get_object('arms_submove')
        self.torso_combobox = self.builder.get_object('torso_submove')
        self.head_combobox = self.builder.get_object('head_submove')
        self.standup_combobox = self.builder.get_object('comboboxstd')

        reps = self.builder.get_object('reps').get()
        reps_label = self.builder.get_object('reps_label')
        reps_label.config(text="Reps: " + str(int(float(reps))))

    def run(self):
        self.mainwindow.mainloop()

    def load_standup_config(self):
        with open("./data/standups.yaml", 'r') as stream:
            self.standup_cfg = yaml.safe_load(stream)

    def on_closing(self):
        """ Close operation. """
        self.thread_alive = False
        self.top_level.destroy()

    def output_text(self, text):
        """ Write to GUI console. """
        output = self.builder.get_object('output')
        output.config(text=text)

    def change_language(self, lang):
        fncts = {"cz": self.robot.set_czech_language,
                 "en": self.robot.set_english_language}
        fncts[lang]()
        self.language = lang

    # key and mouse callbacks
    def on_motorics_clicked(self, even=None):  # take focus
        self.motorics.focus_set()

    def on_w_pressed(self, event=None):
        self.on_forward_clicked()

    def on_a_pressed(self, event=None):
        self.on_left_clicked()

    def on_s_pressed(self, event=None):
        self.on_backward_clicked()

    def on_d_pressed(self, event=None):
        self.on_right_clicked()


    def on_space_pressed(self, event=None):
        self.on_stop_clicked()

    # widget callbacks

    def on_connect_clicked(self):
        PepperIP = self.builder.tkvariables['ipaddress'].get()
        port = self.builder.tkvariables['port'].get()
        if self.robot == None:
            self.ip_address = PepperIP
            self.port = port
            self.robot = Pepper(self.ip_address, self.port)
            self.change_language(self.language)
            self.set_scales()
            # auto life setup
            state = self.robot.autonomous_life_service.getState()
            label = self.builder.get_object('auto_life')
            if state == "disabled":
                label.config(text="Auto Life: OFF")
                self.output_text("[INFO]: Autonomous life off.")
            else:
                label.config(text="Auto Life: ON")
                self.output_text("[INFO]: Autonomous life on.")
            self.output_text("[INFO]: Robot is initialized at " +
                             self.ip_address + ":" + str(port))
            # motion parser
            self.mp = MotionParser(os.path.join(PROJECT_PATH,"workout_conf.json"), self.robot)
            self.arms_combobox['values'] = self.mp.get_conf(
            )["arms_positions"]["data_list"].keys()
            self.head_combobox['values'] = self.mp.get_conf(
            )["head_positions"]["data_list"].keys()
            self.torso_combobox['values'] = self.mp.get_conf(
            )["torso_positions"]["data_list"].keys()
            self.work_dict = {"short_neck": random.sample(range(len(self.mp.get_conf()["workouts"]["short_neck"])), len(self.mp.get_conf()["workouts"]["short_neck"])),
                              "short_arms": random.sample(range(len(self.mp.get_conf()["workouts"]["short_arms"])), len(self.mp.get_conf()["workouts"]["short_arms"])),
                              "short_torso": random.sample(range(len(self.mp.get_conf()["workouts"]["short_torso"])), len(self.mp.get_conf()["workouts"]["short_torso"])),
                              "short_shoulders": random.sample(range(len(self.mp.get_conf()["workouts"]["short_shoulders"])), len(self.mp.get_conf()["workouts"]["short_shoulders"]))
                              }
            self.standup_combobox["values"] = self.standup_cfg["Names"]
            #print(self.work_dict)
        else:
            self.output_text("[INFO]: Already connected to " + self.ip_address)

    def on_czech_clicked(self):
        self.output_text("[INFO]: Language changed to czech.")
        self.change_language("cz")

    def on_english_clicked(self):
        self.change_language("en")
        self.output_text("[INFO]: Language changed to english.")

    def on_blink_clicked(self):
        self.robot.blink_eyes([148,0,211])
        self.output_text("[INFO]: Blinking eyes.")

    def on_stay_clicked(self):
        self.robot.stand()
        self.output_text("[INFO]: Robot is in default position.")

    def on_wave_clicked(self):
        self.robot.start_animation(
            np.random.choice(["Hey_1", "Hey_3", "Hey_4", "Hey_6"]))
        self.output_text("[INFO]: Waving animation.")

    def on_say_clicked(self):
        text_to_say = self.builder.tkvariables['text_to_say'].get()
        self.robot.say(text_to_say.encode("utf-8"))
        self.output_text("[INFO]: Saying \'" + text_to_say + "\'")

    def on_yes_clicked(self):
        text_list = self.configuration.conf["language"][self.language]["yes_list"]
        text = np.random.choice(text_list).encode("utf-8")
        self.robot.say(text)
        self.output_text("[INFO]: Saying yes.")

    def on_no_clicked(self):
        text_list = self.configuration.conf["language"][self.language]["no_list"]
        text = np.random.choice(text_list).encode("utf-8")
        self.robot.say(text)
        self.output_text("[INFO]: Saying no.")

    def on_greet_clicked(self):
        text_list = self.configuration.conf["language"][self.language]["hello"]
        text = np.random.choice(text_list).encode("utf-8")
        self.robot.say(text)
        self.output_text("[INFO]: Greeting.")

    def on_idk_clicked(self):
        text_list = self.configuration.conf["language"][self.language]["dont_know_list"]
        text = np.random.choice(text_list).encode("utf-8")
        qi.async(lambda: self.robot.say(text))
        self.output_text("[INFO]: Saying I don\'t know.")

    def start_stream(self):
        self.robot.subscribe_camera(self.get_picked_camera(), 2, 30)
        self.thread_alive = True
        while self.thread_alive:
            if not self.stream_on:
                continue
            image = self.robot.get_camera_frame(show=False)
            image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
            im = Image.fromarray(image)
            #name = "camera.jpg"
            #im.save(name)
            try:
                # Load image in canvas
                #fpath = os.path.join(PROJECT_PATH, 'camera.jpg')
                #aux = Image.open(im)
                aux = im.resize((320, 240), Image.ANTIALIAS)
                self.img =  ImageTk.PhotoImage(image=aux)
                self.canvas.create_image(0, 0, image=self.img, anchor='nw')
            except:
                print("The application has finished")
                break

    def on_start_stream_clicked(self):
        self.output_text("[INFO]: Starting camera stream.")
        if self.stream_on == -1:
            self.stream_on = 1
            self.video_thread.start()
        else:
            self.stream_on = 1

    def on_stop_stream_clicked(self):
        self.output_text("[INFO]: Stopping camera stream.")
        self.stream_on = 0

    def on_left_clicked(self):
        koeff = self.builder.tkvariables['move_speed'].get()
        if self.movement_state != "left":
            self.robot.motion_service.stopMove()
            self.robot.turn_around(0.55*koeff)
            self.movement_state = "left"
        self.output_text("[INFO]: Turn left.")

    def on_right_clicked(self):
        koeff = self.builder.tkvariables['move_speed'].get()
        if self.movement_state != "right":
            self.robot.motion_service.stopMove()
            self.robot.turn_around(-0.55*koeff)
            self.movement_state = "right"
        self.output_text("[INFO]: Turn right.")

    def on_forward_clicked(self):
        koeff = self.builder.tkvariables['move_speed'].get()
        if self.movement_state != "forw":
            self.robot.motion_service.stopMove()
            self.robot.move_forward(0.2*koeff)
            self.movement_state = "forw"
        self.output_text("[INFO]: Move forward.")

    def on_backward_clicked(self):
        koeff = self.builder.tkvariables['move_speed'].get()
        if self.movement_state != "back":
            self.robot.motion_service.stopMove()
            self.robot.move_forward(-0.2*koeff)
            self.movement_state = "back"
        self.output_text("[INFO]: Move backward.")

    def on_stop_clicked(self):
        self.movement_state = "stop"
        self.robot.motion_service.stopMove()
        self.output_text("[INFO]: Stopping movement.")

    def on_auto_life_clicked(self):
        self.robot.autonomous_life()
        state = self.robot.autonomous_life_service.getState()
        label = self.builder.get_object('auto_life')
        if state == "disabled":
            label.config(text="Auto Life: OFF")
            self.output_text("[INFO]: Autonomous life off.")
        else:
            label.config(text="Auto Life: ON")
            self.output_text("[INFO]: Autonomous life on.")

    def on_reset_tablet_clicked(self):
        self.robot.reset_tablet()
        self.output_text("[INFO]: Reseting tablet.")

    def on_aware_on_clicked(self):
        self.robot.set_awareness(on=True)
        self.output_text("[INFO]: Awarness on.")

    def on_aware_off_clicked(self):
        self.robot.set_awareness(on=False)
        self.output_text("[INFO]: Awarness off.")

    def on_close_app_clicked(self):
        self.robot.stop_behaviour()
        self.robot.tts.stopAll()
        self.output_text("[INFO]: Stopping all behaviour.")

    def on_battery_level_clicked(self):
        self.robot.battery_status()
        self.output_text("[INFO]: Saying my battery level.")

    def on_app_clicked(self, widget_id):
        self.output_text("[INFO]: Running app: " +
                         self.configuration.conf[widget_id]["name"] + ".")
        if widget_id == "application_4":
            self.robot.say("Pojďte zjistit, jak jste na tom se svou pozorností.")
        self.robot.start_behavior(
            self.configuration.conf[widget_id]["package"])

    def on_gesture_clicked(self, widget_id):
        self.output_text("[INFO]: Doing gesture: " +
                         self.configuration.conf[widget_id]["name"] + ".")
        path = np.random.choice(
            self.configuration.conf[widget_id]["path_list"])
        self.animation_from_path(path)

    def on_recognize_clicked(self):
        self.output_text("[INFO]: Recognizing human.")
        recognize_person(self.robot, self.language)

    def on_take_picture_clicked(self):
        self.output_text("[INFO]: Taking picture.")
        take_picture_show(self.robot)

    def on_basic_demo_clicked(self):
        self.output_text("[INFO]: Running basic demo.")

    def on_unlearn_clicked(self):
        self.robot.face_detection_service.clearDatabase()

    ####### ZIVOT 90 ########
    def on_intro_clicked(self):
        self.output_text("[INFO]: Introducing Pepper.")
        text_list = self.configuration.conf["language"][self.language]["introduce"]
        text = np.random.choice(text_list).encode("utf-8")
        qi.async(lambda: self.robot.say(text))

    def on_logo_clicked(self):
        self.output_text("[INFO]: Showing logo Zivot 90.")
        self.robot.show_image("http://people.ciirc.cvut.cz/~sejnogab/zivot90.png")

    def on_offer_clicked(self):
        self.output_text("[INFO]: Offering what to do.")
        text_list = self.configuration.conf["language"][self.language]["offer"]
        text = np.random.choice(text_list).encode("utf-8")
        qi.async(lambda: self.robot.say(text))

    def on_howto_clicked(self):
        self.output_text("[INFO]: Explaining how to talk to robot.")
        text_list = self.configuration.conf["language"][self.language]["how_to"]
        text = np.random.choice(text_list).encode("utf-8")
        qi.async(lambda: self.robot.say(text))

    def on_standup1_clicked(self):
        self.output_text("[INFO]: Running standup 1.")
        text_list = self.configuration.conf["language"][self.language]["standup_1"]
        text = np.random.choice(text_list).encode("utf-8").replace("*wait*", "\\pau=4000\\")
        qi.async(lambda: self.robot.say(text))

    def on_standup2_clicked(self):
        self.output_text("[INFO]: Standup 2 is not defined!")

    def on_standup3_clicked(self):
        self.output_text("[INFO]: Standup 3 is not defined!")

    def on_sorry_clicked(self):
        self.output_text("[INFO]: Saying sorry")
        text_list = self.configuration.conf["language"][self.language]["say_sorry"]
        text = np.random.choice(text_list).encode("utf-8")
        qi.async(lambda: self.robot.say(text))

    def on_alquist_clicked(self):
        self.output_text("[INFO]: Running Alquist")
        if "10.37." in self.ip_address:
            self.robot.start_behavior("alquist-9640b1/behavior_1")
        else:
            self.robot.start_behavior("alquist-9640b1/behavior_2")

    def on_chatbottwo_clicked(self):
        self.output_text("[INFO]: Running Chatbot 2")
        path = "/home/martin/chatbot2"
        src_path = os.path.join(path, "src")
        main_path = os.path.join(src_path, "main.py")
        data_path = os.path.join(path, "data")
        logs_path = os.path.join(path, "logs")
        command = "sudo PYTHONPATH=${PYTHONPATH}:/home/martin/pynaoqi-python2.7-2.5.7.1-linux64/lib/python2.7/site-packages python2 " + main_path + " --robot-credentials " + self.ip_address + " --mode robot_remote --data-dir " + data_path + " --logs-dir " + logs_path + " --loglevel-file trace --loglevel-console info"
        subprocess.call("gnome-terminal -- " + command, shell=True)

    def on_dance_clicked(self):
        self.output_text("[INFO]: Dancing")
        self.robot.start_behavior("date_dance-896e88/")

    def on_getname_clicked(self):
        self.output_text("[INFO]: Trying to recognize person")
        recognize_person(self.robot, self.language)

    def on_howdy_clicked(self):
        self.output_text("[INFO]: Asking how are you")
        text_list = self.configuration.conf["language"][self.language]["how_are_you"]
        text = np.random.choice(text_list).encode("utf-8")
        qi.async(lambda: self.robot.say(text))

    def on_iamfine_clicked(self):
        self.output_text("[INFO]: Saying I am fine")
        text_list = self.configuration.conf["language"][self.language]["i_am_fine"]
        text = np.random.choice(text_list).encode("utf-8")
        qi.async(lambda: self.robot.say(text))

    def on_andyou_clicked(self):
        self.output_text("[INFO]: Asking How about you?")
        text_list = self.configuration.conf["language"][self.language]["and_you"]
        text = np.random.choice(text_list).encode("utf-8")
        qi.async(lambda: self.robot.say(text))

    def on_say_standup(self):
        self.output_text("[INFO]: Saying standup")
        title = self.builder.get_object('comboboxstd').get()
        for k in self.standup_cfg.keys():
            if not isinstance(self.standup_cfg[k], list):
                if self.standup_cfg[k]["id"] == title:
                    text = self.standup_cfg[k]["text"].encode("utf-8")
        if not "centrum" in title:
            if self.ask_for_standup(title):
                qi.async(lambda: self.robot.say(text.replace("*wait*", "\\pau=4000\\")))
            else:
                self.robot.say(random.choice(["Dobře", "ok", "nevadí"]))
        else:
            qi.async(lambda: self.robot.say(text))

    def ask_for_standup(self, title):
        self.robot.say(random.choice(self.standup_cfg["Dotaz"]).format(title).encode("utf-8"))
        positive_answers = ["ano", "dobře", "tak dobře", "tak jo", "ok", "chci", "ale jo", "chceme", "jasně", "určite", "jo", "nevím"]
        vocab = positive_answers + ["ne", "nechci", "nechceme", "to ne", "ale ne"]
        answer = self.robot.listen_to(vocabulary=vocab)
        if answer[0].lower() in positive_answers:
            return True
        else:
            return False


    def on_update_sound_clicked(self):
        self.output_text("[INFO]: Updating sound settings.")
        volume = self.builder.tkvariables['volume'].get()
        voice_pitch = self.builder.tkvariables['voice_pitch'].get()
        voice_speed = self.builder.tkvariables['voice_speed'].get()
        self.robot.changeVoice(volume, voice_speed, voice_pitch)

    def on_update_chatbot_clicked(self):
        self.output_text("[INFO]: Updating chatbot settings.")
        self.chatbot_voice_stop = self.builder.tkvariables['voice_stopped'].get() * 1000
        self.chatbot_voice_sens = self.builder.tkvariables['voice_sensitivity'].get()
        self.chatbot_person_left = self.builder.tkvariables['person_left'].get() * 1000

    def set_scales(self):
        self.builder.tkvariables['voice_speed'].set(self.robot.getVoiceSpeed())
        self.builder.tkvariables['voice_pitch'].set(self.robot.getVoiceShape())
        self.builder.tkvariables['volume'].set(self.robot.getVoiceVolume())

    def animation_from_path(self, path):
        try:
            if self.robot.eye_blinking_enabled:
                self.robot.speech_service.setAudioExpression(True)
                self.robot.speech_service.setVisualExpression(True)
            else:
                self.robot.speech_service.setAudioExpression(False)
                self.robot.speech_service.setVisualExpression(False)

            animation_finished = self.robot.animation_service.run(
                "animations/[posture]/" + path, _async=True)
            animation_finished.value()

            return True
        except Exception as error:
            print(error)
            return False

    def on_pick_camera_clicked(self, a, b):
        camera_id = self.builder.get_object('pick_camera').current()
        if camera_id == 2:
            camera = "camera_depth"
        elif camera_id == 1:
            camera = "camera_bottom"
        else:
            camera = "camera_top"
        self.robot.subscribe_camera(camera, 2, 30)

    def get_picked_camera(self):
        """ Get picked camera from combobox. """
        camera_id = self.builder.get_object('pick_camera').current()
        if camera_id == 2:
            camera = "camera_depth"
        elif camera_id == 1:
            camera = "camera_bottom"
        else:
            camera = "camera_top"
        return camera

    def on_picked_camera(self, event):
        """ Combobox event. """
        camera_name = event.widget.get()
        if camera_name == "Camera Depth":
            camera = "camera_depth"
        elif camera_name == "Camera Bottom":
            camera = "camera_bottom"
        else:
            camera = "camera_top"
        self.robot.subscribe_camera(camera, 2, 30)

    def on_handshake_clicked(self):
        self.robot.do_hand_shake()

    def on_do_move_clicked(self):
        state = self.robot.autonomous_life_service.getState()
        if state != "disabled":
            self.robot.autonomous_life_off()
        arms = self.builder.get_object('arms_submove').get()
        torso = self.builder.get_object('torso_submove').get()
        head = self.builder.get_object('head_submove').get()
        self.mp.go_to_position(head, torso, arms, 0.2)

    def on_random_work_clicked(self, group):
        state = self.robot.autonomous_life_service.getState()
        if state != "disabled":
            self.robot.autonomous_life_off()
        #work = self.work_list[widget_id]
        reps = self.builder.get_object('reps').get()
        reps = int(float(reps))
        # order = {0: "short_neck",
        #          1: "short_torso",
        #          2: "short_arms",
        #          3: "short_shoulders"}
        #group = order[widget_id]
        #print(self.work_dict[group])
        index = self.work_dict[group].pop(0)
        self.work_dict[group].append(index)
        #print(self.work_dict[group])
        self.mp.do_workout(group, index, reps)
        # for i in range(len(work)):
        #    head = work[0][i][0]
        #    torso = work[0][i][1]
        #    arms = work[0][i][2]
        #    workout.go_to_position(head, torso, arms, 0.2)
        # work = work[1:]+[work[0]]
        # print(work)
        # print(self.work_list[widget_id])

    def on_reps_changed(self, scale_value):
        label = self.builder.get_object('reps_label')
        label.config(text="Reps: " + str(int(float(scale_value))))

    def on_chatbot_clicked(self):
        print("running chatbot")
        path = self.builder.get_object('path_to_chatbot').cget("path")
        src_path = os.path.join(path, "src")
        main_path = os.path.join(src_path, "main.py")
        data_path = os.path.join(path, "data")
        logs_path = os.path.join(path, "logs")
        #subprocess.call('gnome-terminal -- {} --mode robot_remote --data-dir {} --logs-dir {} --loglevel-file trace --loglevel-console info'.format(main_path, data_path, logs_path), shell=True, cwd=src_path)
        #print('gnome-terminal -- {} --mode robot_remote --data-dir {} --logs-dir {} --loglevel-file trace --loglevel-console info'.format(main_path, data_path, logs_path))
        
        #command = "python " + main_path + " -m robot_remote -l " + logs_path +" -d " + data_path
        command = "python " + main_path + " --robot-credentials " + self.ip_address + " --mode robot_remote --data-dir " + data_path + " --logs-dir " + logs_path +" --loglevel-file trace --loglevel-console info"
        subprocess.call("gnome-terminal -- " + command, shell=True)

        #subprocess.call("gnome-terminal -- ./run_chatbot.sh " + main_path + " " + data_path + " " + logs_path, shell=True)

    def on_default_path_clicked(self):
        conf = self.configuration.conf
        path = conf["default_chatbot_path"]
        self.builder.get_object('path_to_chatbot')["path"] = conf["default_chatbot_path"]

    def on_restart_clicked(self):
        self.output_text("[INFO]: Restarting robot.")
        self.robot.restart_robot()


if __name__ == '__main__':
    app = PepperControllerApp()
    app.run()
