# -*- coding: utf-8 -*-
import re
import time
import unittest

from selenium import webdriver
from selenium.common.exceptions import NoAlertPresentException, NoSuchElementException
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import Select

from app.test.interfaz.selenium_compat import create_driver

BUTTON = "//button[@id='nav-open-menu']/span"
CLOSE_SESSION = u"(.//*[normalize-space(text()) and normalize-space(.)='Cerrar sesión'])[1]/following::ol[1]"
MAIN_PAGE = u"(.//*[normalize-space(text()) and normalize-space(.)='Página principal'])[2]/following::li[1]"
LOG_OUT = "(.//*[normalize-space(text()) and normalize-space(.)='Log out'])[1]/following::ol[1]"

class Navegacion(unittest.TestCase):
    def setUp(self):
        self.driver = create_driver()
        self.driver.implicitly_wait(30)
        self.base_url = "https://www.google.com/"
        self.verificationErrors = []
        self.accept_next_alert = True
    
    def test_navegacion(self):
        driver = self.driver
        driver.get("https://pythia.es/")
        driver.find_element_by_link_text(u"Iniciar sesión").click()
        driver.find_element_by_id("email").click()
        driver.find_element_by_id("email").clear()
        driver.find_element_by_id("email").send_keys("admin@gmail.com")
        driver.find_element_by_id("password").click()
        driver.find_element_by_id("password").clear()
        driver.find_element_by_id("password").send_keys(u"contraseña")
        driver.find_element_by_id("submit").click()
        driver.find_element_by_xpath(u"(.//*[normalize-space(text()) and normalize-space(.)='Cerrar sesión'])[1]/following::nav[1]").click()
        self.assertEqual(u"Página principal", driver.find_element_by_xpath(u"(.//*[normalize-space(text()) and normalize-space(.)='Cerrar sesión'])[1]/following::li[1]").text)
        driver.find_element_by_xpath(BUTTON).click()
        driver.find_element_by_id("nav-history").click()
        driver.find_element_by_xpath(CLOSE_SESSION).click()
        self.assertEqual("Historial de consultas", driver.find_element_by_xpath(MAIN_PAGE).text)
        driver.find_element_by_xpath(BUTTON).click()
        driver.find_element_by_id("nav-profile").click()
        driver.find_element_by_xpath(CLOSE_SESSION).click()
        self.assertEqual("Perfil de Usuario", driver.find_element_by_xpath(MAIN_PAGE).text)
        driver.find_element_by_xpath(BUTTON).click()
        driver.find_element_by_id("nav-stats").click()
        driver.find_element_by_xpath(CLOSE_SESSION).click()
        self.assertEqual(u"Estadísticas", driver.find_element_by_xpath(MAIN_PAGE).text)
        driver.find_element_by_xpath(BUTTON).click()
        driver.find_element_by_id("nav-docs").click()
        driver.find_element_by_xpath(MAIN_PAGE).click()
        self.assertEqual("Administrar documentos", driver.find_element_by_xpath(MAIN_PAGE).text)
        driver.find_element_by_xpath(BUTTON).click()
        driver.find_element_by_id("nav-users").click()
        driver.find_element_by_xpath(CLOSE_SESSION).click()
        self.assertEqual(u"Gestión de usuarios", driver.find_element_by_xpath(MAIN_PAGE).text)
        driver.find_element_by_xpath(BUTTON).click()
        driver.find_element_by_xpath("//div[@id='nav-i18n']/form[2]/button").click()
        driver.find_element_by_xpath(LOG_OUT).click()
        self.assertEqual("User management", driver.find_element_by_xpath("(.//*[normalize-space(text()) and normalize-space(.)='Home'])[2]/following::li[1]").text)
        driver.find_element_by_xpath(BUTTON).click()
        driver.find_element_by_id("nav-theme-light").click()
        driver.find_element_by_id("nav-theme-dark").click()
        driver.find_element_by_xpath("//div[4]").click()
        driver.find_element_by_id("nav-logo-home").click()
        driver.find_element_by_xpath(LOG_OUT).click()
        self.assertEqual("Home", driver.find_element_by_xpath("(.//*[normalize-space(text()) and normalize-space(.)='Log out'])[1]/following::li[1]").text)
        driver.get("https://pythia.es/rag")
        driver.find_element_by_xpath(LOG_OUT).click()
        self.assertEqual("Query the model", driver.find_element_by_xpath("(.//*[normalize-space(text()) and normalize-space(.)='Home'])[2]/following::li[1]").text)
        driver.find_element_by_xpath(BUTTON).click()
        driver.find_element_by_xpath("//button[@type='submit']").click()
        driver.find_element_by_xpath(BUTTON).click()
        driver.find_element_by_id("nav-logout").click()
        driver.find_element_by_xpath("(.//*[normalize-space(text()) and normalize-space(.)='Registrarse'])[1]/following::span[1]").click()
        self.assertEqual("Responde todas tus preguntas", driver.find_element_by_xpath("(.//*[normalize-space(text()) and normalize-space(.)='Registrarse'])[1]/following::span[1]").text)
    
    def is_element_present(self, how, what):
        try: self.driver.find_element(by=how, value=what)
        except NoSuchElementException: return False
        return True
        
    def tearDown(self):
        self.driver.quit()
        self.assertEqual([], self.verificationErrors)

if __name__ == "__main__":
    unittest.main()
