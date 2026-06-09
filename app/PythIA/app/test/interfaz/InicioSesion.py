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


class InicioSesion(unittest.TestCase):
    def setUp(self):
        self.driver = create_driver()
        self.driver.implicitly_wait(30)
        self.base_url = "https://www.google.com/"
        self.verificationErrors = []
        self.accept_next_alert = True
    
    def test_inicio_sesion(self):
        driver = self.driver
        driver.get("https://pythia.es/")
        driver.get("https://pythia.es/login")
        driver.find_element_by_xpath(u"(.//*[normalize-space(text()) and normalize-space(.)='Inicio de sesión'])[2]/following::h1[1]").click()
        self.assertEqual(u"Inicio de sesión", driver.title)
        driver.find_element_by_id("email").click()
        driver.find_element_by_id("email").clear()
        driver.find_element_by_id("email").send_keys("ad@gmail.com")
        driver.find_element_by_id("submit").click()
        driver.find_element_by_xpath("(.//*[normalize-space(text()) and normalize-space(.)='Revisa los errores del formulario.'])[1]/following::li[1]").click()
        self.assertEqual(u"Contraseña:", driver.find_element_by_xpath("(.//*[normalize-space(text()) and normalize-space(.)='Revisa los errores del formulario.'])[1]/following::span[1]").text)
        driver.find_element_by_id("password").click()
        driver.find_element_by_id("password").clear()
        driver.find_element_by_id("password").send_keys(u"contraseña")
        driver.find_element_by_id("submit").click()
        driver.find_element_by_xpath("(.//*[normalize-space(text()) and normalize-space(.)='Revisa los errores del formulario.'])[1]/following::li[1]").click()
        self.assertEqual(u"Contraseña:", driver.find_element_by_xpath("(.//*[normalize-space(text()) and normalize-space(.)='Revisa los errores del formulario.'])[1]/following::span[1]").text)
        driver.find_element_by_id("email").click()
        driver.find_element_by_id("email").send_keys(Keys.DOWN)
        driver.find_element_by_id("email").clear()
        driver.find_element_by_id("email").send_keys("admin@gmail.com")
        driver.find_element_by_id("password").click()
        driver.find_element_by_id("password").clear()
        driver.find_element_by_id("password").send_keys(u"contraseña")
        driver.find_element_by_id("submit").click()
        driver.get("https://pythia.es/pagina_principal")
        driver.find_element_by_xpath(u"(.//*[normalize-space(text()) and normalize-space(.)='Cerrar sesión'])[1]/following::ol[1]").click()
        self.assertEqual(u"Página principal", driver.find_element_by_xpath(u"(.//*[normalize-space(text()) and normalize-space(.)='Cerrar sesión'])[1]/following::li[1]").text)
        driver.find_element_by_xpath("//button[@id='nav-open-menu']/span").click()
        driver.find_element_by_id("nav-logout").click()
        driver.get("https://pythia.es/")
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
