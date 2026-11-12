# Selenium: automation of browser
from selenium import webdriver
# from webdriver_manager.chrome import ChromeDriverManager
import undetected_chromedriver as uc
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException, TimeoutException, ElementNotVisibleException, SessionNotCreatedException
from selenium.webdriver.common.by import By


# some other imports :-)
import os
import platform
import time
import random
import re
import requests
import atexit
from pathlib import Path

# Tinderbotz: helper classes
from loveworm.helpers.geomatch import Geomatch
from loveworm.helpers.match import Match
from loveworm.helpers.profile_helper import ProfileHelper
from loveworm.helpers.preferences_helper import PreferencesHelper
from loveworm.helpers.geomatch_helper import GeomatchHelper
from loveworm.helpers.match_helper import MatchHelper
from loveworm.helpers.login_helper import LoginHelper
from loveworm.helpers.storage_helper import StorageHelper
from loveworm.helpers.constants_helper import Printouts
from loveworm.helpers.xpaths import *
from loveworm.helpers import fisico
from loveworm.addproxy import get_proxy_extension


class Session:
    HOME_URL = "https://www.tinder.com/app/recs"

    # fuera de la vista: Chrome sigue dibujando y respondiendo (a diferencia de minimizado, que congela
    # las animaciones), pero no tapa lo que estés haciendo
    OFFSCREEN = (-32000, -32000)

    def __init__(self, headless=False, store_session=True, proxy=None, user_data=False, hidden=False):
        self.hidden = hidden
        self.email = None
        self.session_data = {
            "duration": 0,
            "like": 0,
            "dislike": 0,
            "superlike": 0
        }

        start_session = time.time()

        # this function will run when the session ends
        @atexit.register
        def cleanup():
            # End session duration
            seconds = int(time.time() - start_session)
            self.session_data["duration"] = seconds

            # add session data into a list of messages
            lines = []
            for key in self.session_data:
                message = "{}: {}".format(key, self.session_data[key])
                lines.append(message)

            # print out the statistics of the session
            try:
                box = self._get_msg_box(lines=lines, title="Tinderbotz")
                print(box)
            finally:
                print("Started session: {}".format(self.started))
                y = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
                print("Ended session: {}".format(y))

            # Close browser properly
            self.browser.quit()

        # Getting the chromedriver from cache or download it from internet
        print("Getting ChromeDriver ...")
        try:
            self.browser = uc.Chrome(options=self._options(store_session, user_data, headless, proxy, hidden))
        except SessionNotCreatedException as e:
            # uc baja el driver de la última versión de Chrome; si el instalado es otra, reintenta con esa
            m = re.search(r"Current browser version is (\d+)", str(e))
            if not m:
                raise
            print(f"ChromeDriver no coincide, reintentando para Chrome {m.group(1)} ...")
            self.browser = uc.Chrome(options=self._options(store_session, user_data, headless, proxy, hidden),
                                     version_main=int(m.group(1)))

        # Cool banner
        print(Printouts.BANNER.value)
        time.sleep(1)

        self.started = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        print("Started session: {}\n\n".format(self.started))

    # uc no deja reusar unas ChromeOptions entre intentos, así que se arman de cero cada vez
    @staticmethod
    def _options(store_session, user_data, headless, proxy, hidden=False):
        options = uc.ChromeOptions()
        # que siga andando a velocidad normal aunque esté tapado o fuera de la vista
        for flag in ("--disable-backgrounding-occluded-windows", "--disable-renderer-backgrounding",
                     "--disable-background-timer-throttling"):
            options.add_argument(flag)
        if hidden:
            options.add_argument("--window-position={},{}".format(*Session.OFFSCREEN))

        # Create empty profile to avoid annoying Mac Popup
        if store_session:
            if not user_data:
                user_data = f"{Path().absolute()}/chrome_profile/"
            if not os.path.isdir(user_data):
                os.mkdir(user_data)

            Path(f'{user_data}First Run').touch()
            options.add_argument(f"--user-data-dir={user_data}")

        #options.add_argument("--start-maximized")
        options.add_argument('--no-first-run --no-service-autorun --password-store=basic')
        options.add_argument("--lang=en-GB")

        if headless:
            options.headless = True

        if proxy:
            if '@' in proxy:
                parts = proxy.split('@')

                user = parts[0].split(':')[0]
                pwd = parts[0].split(':')[1]

                host = parts[1].split(':')[0]
                port = parts[1].split(':')[1]

                extension = get_proxy_extension(PROXY_HOST=host, PROXY_PORT=port, PROXY_USER=user, PROXY_PASS=pwd)
                options.add_extension(extension)
            else:
                options.add_argument(f'--proxy-server=http://{proxy}')
        return options

    def show_window(self):
        """Trae el Chrome del bot a la vista (por ejemplo, para iniciar sesión)."""
        self.hidden = False
        self.browser.set_window_rect(x=80, y=60, width=1200, height=900)
        self.browser.switch_to.window(self.browser.current_window_handle)  # lo pasa al frente

    def hide_window(self):
        """Lo saca de la vista sin minimizarlo, así sigue swipeando y no se roba el foco."""
        self.hidden = True
        x, y = Session.OFFSCREEN
        self.browser.set_window_rect(x=x, y=y, width=1200, height=900)

    # Setting a custom location
    def set_custom_location(self, latitude, longitude, accuracy="100%"):

        params = {
            "latitude": latitude,
            "longitude": longitude,
            "accuracy": int(accuracy.split('%')[0])
        }

        self.browser.execute_cdp_cmd("Page.setGeolocationOverride", params)

    # NOTE: Need to be logged in for this
    def set_distance_range(self, km):
        helper = PreferencesHelper(browser=self.browser)
        helper.set_distance_range(km)

    def set_age_range(self, min, max):
        helper = PreferencesHelper(browser=self.browser)
        helper.set_age_range(min, max)

    def set_sexuality(self, type):
        helper = PreferencesHelper(browser=self.browser)
        helper.set_sexualitiy(type)

    def set_global(self, boolean):
        helper = PreferencesHelper(browser=self.browser)
        helper.set_global(boolean)

    def set_bio(self, bio):
        helper = ProfileHelper(browser=self.browser)
        helper.set_bio(bio)

    def add_photo(self, filepath):
        helper = ProfileHelper(browser=self.browser)
        helper.add_photo(filepath)

    # Actions of the session
    def login_using_google(self, email, password):
        self.email = email
        if not self._is_logged_in():
            helper = LoginHelper(browser=self.browser)
            helper.login_by_google(email, password)
            time.sleep(5)
        if not self._is_logged_in():
            print('Manual interference is required.')
            input('press ENTER to continue')

    def login_using_facebook(self, email, password):
        self.email = email
        if not self._is_logged_in():
            helper = LoginHelper(browser=self.browser)
            helper.login_by_facebook(email, password)
            time.sleep(5)
        if not self._is_logged_in():
            print('Manual interference is required.')
            input('press ENTER to continue')

    def login_using_sms(self, country, phone_number):
        if not self._is_logged_in():
            helper = LoginHelper(browser=self.browser)
            helper.login_by_sms(country, phone_number)
            time.sleep(5)
        if not self._is_logged_in():
            print('Manual interference is required.')
            input('press ENTER to continue')

    # opens tinder and waits until the user logs in by hand (google, facebook, sms...)
    def login_manually(self):
        if not self._is_logged_in():
            print("\n\nINICIÁ SESIÓN A MANO EN EL CHROME (Log in -> Google)\n")
            while "tinder.com/app/" not in self.browser.current_url:
                time.sleep(1)
            time.sleep(3)

        LoginHelper(browser=self.browser)._handle_popups()

    def store_local(self, match):
        if isinstance(match, Match):
            filename = 'matches'
        elif isinstance(match, Geomatch):
            filename = 'geomatches'
        else:
            print("type of match is unknown, storing local impossible")
            print("Crashing in 3.2.1... :)")
            assert False

        # store its images
        for url in match.image_urls:
            hashed_image = StorageHelper.store_image_as(url=url, directory='data/{}/images'.format(filename))
            match.images_by_hashes.append(hashed_image)

        # store its userdata
        StorageHelper.store_match(match=match, directory='data/{}'.format(filename), filename=filename)

    # stop_event: optional threading.Event that ends the loop early when set
    # filtro: Filtro de helpers/fisico.py; decide like/dislike en vez del ratio aleatorio
    def like(self, amount=1, ratio='100%', sleep=1, randomize_sleep=True, stop_event=None, filtro=None):

        initial_sleep = sleep
        ratio = float(ratio.split('%')[0]) / 100

        if self._is_logged_in():
            helper = GeomatchHelper(browser=self.browser)
            amount_liked = 0
            # handle one time up front, from then on check after every action instead of before
            self._handle_potential_popups()
            print("\nLiking profiles started.")
            while amount_liked < amount:
                if stop_event is not None and stop_event.is_set():
                    print("Liking stopped.")
                    break
                if filtro is not None and filtro.agotado:
                    print("Filtro agotado (max_vistos).")
                    break
                # randomize sleep
                if randomize_sleep:
                    sleep = random.uniform(0.5, 2.3) * initial_sleep

                # los popups se comen el click: se limpian antes de cada tarjeta, no una sola vez
                self._handle_potential_popups()

                pasar = None
                if filtro is not None:
                    # None = no decide (sombra, sin fotos, error): cae al ratio de siempre
                    pasar = filtro.decidir()
                if pasar is None:
                    pasar = random.random() <= ratio

                if pasar:
                    if helper.like():
                        amount_liked += 1
                        # update for stats after session ended
                        self.session_data['like'] += 1
                        print(f"{amount_liked}/{amount} liked, sleep: {sleep}")
                else:
                    helper.dislike()
                    # update for stats after session ended
                    self.session_data['dislike'] += 1

                time.sleep(sleep)

            self._print_liked_stats()

    def dislike(self, amount=1):
        if self._is_logged_in():
            helper = GeomatchHelper(browser=self.browser)
            for _ in range(amount):
                self._handle_potential_popups()
                helper.dislike()

                # update for stats after session ended
                self.session_data['dislike'] += 1
                #time.sleep(1)
            self._print_liked_stats()

    def superlike(self, amount=1):
        if self._is_logged_in():
            helper = GeomatchHelper(browser=self.browser)
            for _ in range(amount):
                self._handle_potential_popups()
                helper.superlike()

                # update for stats after session ended
                self.session_data['superlike'] += 1
                time.sleep(1)
            self._print_liked_stats()

    def get_geomatch(self, quickload=True):
        if self._is_logged_in():
            helper = GeomatchHelper(browser=self.browser)
            self._handle_potential_popups()

            name = None
            attempts = 0
            max_attempts = 3
            while not name and attempts < max_attempts:
                attempts += 1
                name = helper.get_name()
                self._handle_potential_popups() # Popup handling on first geomatch
                time.sleep(1)

            age = helper.get_age()

            bio, passions, lifestyle, basics, anthem, looking_for = helper.get_bio_and_passions()
            image_urls = helper.get_image_urls(quickload)
            instagram = helper.get_insta(bio)
            rowdata = helper.get_row_data()
            work = rowdata.get('work')
            study = rowdata.get('study')
            home = rowdata.get('home')
            distance = rowdata.get('distance')
            gender = rowdata.get('gender')

            return Geomatch(name=name, age=age, work=work, gender=gender, study=study, home=home, distance=distance,
                            bio=bio, passions=passions, lifestyle=lifestyle, basics=basics, anthem=anthem, looking_for=looking_for, image_urls=image_urls, instagram=instagram)

    def get_chat_ids(self, new=True, messaged=True):
        if self._is_logged_in():
            helper = MatchHelper(browser=self.browser)
            self._handle_potential_popups()
            return helper.get_chat_ids(new, messaged)

    def get_new_matches(self, amount=100000, quickload=True):
        if self._is_logged_in():
            helper = MatchHelper(browser=self.browser)
            self._handle_potential_popups()
            return helper.get_new_matches(amount, quickload)

    def get_messaged_matches(self, amount=100000, quickload=True):
        if self._is_logged_in():
            helper = MatchHelper(browser=self.browser)
            self._handle_potential_popups()
            return helper.get_messaged_matches(amount, quickload)

    def send_message(self, chatid, message):
        if self._is_logged_in():
            helper = MatchHelper(browser=self.browser)
            self._handle_potential_popups()
            helper.send_message(chatid, message)

    def send_gif(self, chatid, gifname):
        if self._is_logged_in():
            helper = MatchHelper(browser=self.browser)
            self._handle_potential_popups()
            helper.send_gif(chatid, gifname)

    def send_song(self, chatid, songname):
        if self._is_logged_in():
            helper = MatchHelper(browser=self.browser)
            self._handle_potential_popups()
            helper.send_song(chatid, songname)

    def send_socials(self, chatid, media):
        if self._is_logged_in():
            helper = MatchHelper(browser=self.browser)
            self._handle_potential_popups()
            helper.send_socials(chatid, media)

    def unmatch(self, chatid):
        if self._is_logged_in():
            helper = MatchHelper(browser=self.browser)
            self._handle_potential_popups()
            helper.unmatch(chatid)

    # Utilities
    def _handle_potential_popups(self):
        delay = 0.25

        # last possible id based div
        base_element = self.browser.find_element(By.XPATH, modal_manager)

        # try to deny see who liked you
        try:
            xpath = './/main/div/div/div[3]/button[2]'
            WebDriverWait(base_element, delay).until(
                EC.presence_of_element_located((By.XPATH, xpath)))

            deny_btn = base_element.find_element(By.XPATH, xpath)
            deny_btn.click()
            return "POPUP: Denied see who liked you"

        except NoSuchElementException:
            pass
        except TimeoutException:
            pass

        # Try to dismiss a potential 'upgrade like' popup
        try:
            # locate "no thanks"-button
            xpath = './/main/div/button[2]'
            base_element.find_element(By.XPATH, xpath).click()
            return "POPUP: Denied upgrade to superlike"
        except NoSuchElementException:
            pass

        # try to deny 'add tinder to homescreen'
        try:
            xpath = './/main/div/div[2]/button[2]'

            add_to_home_popup = base_element.find_element(By.XPATH, xpath)
            add_to_home_popup.click()
            return "POPUP: Denied Tinder to homescreen"

        except NoSuchElementException:
            pass

        # deny buying more superlikes
        try:
            xpath = './/main/div/div[3]/button[2]'
            deny = base_element.find_element(By.XPATH, xpath)
            deny.click()
            return "POPUP: Denied buying more superlikes"
        except NoSuchElementException:
            pass

        # try to dismiss match
        matched = False
        try:
            xpath = '//button[@title="Back to Tinder"]'

            match_popup = base_element.find_element(By.XPATH, xpath)
            match_popup.click()
            matched = True

        except NoSuchElementException:
            pass
        except:
            matched = True
            self.browser.refresh()


        # try to say 'no thanks' to buy more (super)likes
        try:
            xpath = './/main/div/div[3]/button[2]'
            deny_btn = base_element.find_element(By.XPATH, xpath)
            deny_btn.click()
            return "POPUP: Denied buying more superlikes"

        except ElementNotVisibleException:
            # element is not clickable, probably cuz it's out of view but still there
            self.browser.refresh()
        except NoSuchElementException:
            pass
        except:
            # TBD add stale element exception for now just refresh page
            self.browser.refresh()
            pass

        # Deny confirmation of email
        try:
            xpath = './/main/div/div[1]/div[2]/button[2]'
            remindmelater = base_element.find_element(By.XPATH, xpath)
            remindmelater.click()

            time.sleep(3)
            # handle other potential popups
            self._handle_potential_popups()
            return "POPUP: Deny confirmation of email"
        except:
            pass

        # Deny add location popup
        try:
            xpath = ".//*[contains(text(), 'No Thanks')]"
            nothanks = base_element.find_element(By.XPATH, xpath)
            nothanks.click()
            time.sleep(3)
            # handle other potential popups
            self._handle_potential_popups()
            return "POPUP: Deny confirmation of email"
        except:
            pass

        return None

    def _is_logged_in(self):
        # make sure tinder website is loaded for the first time
        if not "tinder" in self.browser.current_url:
            # enforce english language
            self.browser.get("https://tinder.com/?lang=en")
            time.sleep(1.5)

        if "tinder.com/app/" in self.browser.current_url:
            return True
        else:
            print("User is not logged in yet.\n")
            return False

    def _get_msg_box(self, lines, indent=1, width=None, title=None):
        """Print message-box with optional title."""
        space = " " * indent
        if not width:
            width = max(map(len, lines))
        box = f'/{"=" * (width + indent * 2)}\\\n'  # upper_border
        if title:
            box += f'|{space}{title:<{width}}{space}|\n'  # title
            box += f'|{space}{"-" * len(title):<{width}}{space}|\n'  # underscore
        box += ''.join([f'|{space}{line:<{width}}{space}|\n' for line in lines])
        box += f'\\{"=" * (width + indent * 2)}/'  # lower_border
        return box

    def _print_liked_stats(self):
        likes = self.session_data['like']
        dislikes = self.session_data['dislike']
        superlikes = self.session_data['superlike']

        if superlikes > 0:
            print(f"You've superliked {self.session_data['superlike']} profiles during this session.")
        if likes > 0:
            print(f"You've liked {self.session_data['like']} profiles during this session.")
        if dislikes > 0:
            print(f"You've disliked {self.session_data['dislike']} profiles during this session.")