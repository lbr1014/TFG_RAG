# -*- coding: utf-8 -*-
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import Select
from selenium.common.exceptions import NoSuchElementException
from selenium.common.exceptions import NoAlertPresentException
from app.test.interfaz.selenium_compat import create_driver
import unittest, time, re

class RecuperarContraseA(unittest.TestCase):
    def setUp(self):
        self.driver = create_driver()
        self.driver.implicitly_wait(30)
        self.base_url = "https://www.google.com/"
        self.verificationErrors = []
        self.accept_next_alert = True
    
    def test_recuperar_contrase_a(self):
        driver = self.driver
        driver.get("https://pythia.es/")
        driver.find_element_by_xpath("(.//*[normalize-space(text()) and normalize-space(.)='Registrarse'])[1]/following::span[1]").click()
        try: self.assertEqual("Responde todas tus preguntas", driver.find_element_by_xpath("(.//*[normalize-space(text()) and normalize-space(.)='Registrarse'])[1]/following::span[1]").text)
        except AssertionError as e: self.verificationErrors.append(str(e))
        driver.find_element_by_link_text(u"Iniciar sesión").click()
        driver.find_element_by_xpath(u"(.//*[normalize-space(text()) and normalize-space(.)='Inicio de sesión'])[2]/following::h1[1]").click()
        self.assertEqual(u"Inicio de sesión", driver.find_element_by_xpath(u"(.//*[normalize-space(text()) and normalize-space(.)='Inicio de sesión'])[2]/following::h1[1]").text)
        driver.find_element_by_link_text(u"¿Olvidaste tu contraseña?").click()
        driver.find_element_by_xpath(u"(.//*[normalize-space(text()) and normalize-space(.)='Recuperar contraseña'])[2]/following::h1[1]").click()
        self.assertEqual(u"Recuperar contraseña", driver.find_element_by_xpath(u"(.//*[normalize-space(text()) and normalize-space(.)='Recuperar contraseña'])[2]/following::h1[1]").text)
        driver.find_element_by_id("email").click()
        driver.find_element_by_id("email").clear()
        driver.find_element_by_id("email").send_keys("lydiab293@gmail.com")
        driver.find_element_by_id("submit").click()
        driver.find_element_by_xpath(u"(.//*[normalize-space(text()) and normalize-space(.)='Inicio de sesión'])[2]/following::div[3]").click()
        try: self.assertEqual(u"Se ha enviado un enlace para recuperar la contraseña.", driver.find_element_by_xpath(u"(.//*[normalize-space(text()) and normalize-space(.)='Inicio de sesión'])[2]/following::div[3]").text)
        except AssertionError as e: self.verificationErrors.append(str(e))
    
    def is_element_present(self, how, what):
        try: self.driver.find_element(by=how, value=what)
        except NoSuchElementException as e: return False
        return True
    
    def is_alert_present(self):
        try: self.driver.switch_to_alert()
        except NoAlertPresentException as e: return False
        return True
    
    def close_alert_and_get_its_text(self):
        try:
            alert = self.driver.switch_to_alert()
            alert_text = alert.text
            if self.accept_next_alert:
                alert.accept()
            else:
                alert.dismiss()
            return alert_text
        finally: self.accept_next_alert = True
    
    def tearDown(self):
        self.driver.quit()
        self.assertEqual([], self.verificationErrors)

if __name__ == "__main__":
    unittest.main()
