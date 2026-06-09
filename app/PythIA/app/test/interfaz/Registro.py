# -*- coding: utf-8 -*-
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import Select
from selenium.common.exceptions import NoSuchElementException
from selenium.common.exceptions import NoAlertPresentException
from app.test.interfaz.selenium_compat import create_driver
import unittest, time, re

class Registro(unittest.TestCase):
    def setUp(self):
        self.driver = create_driver()
        self.driver.implicitly_wait(30)
        self.base_url = "https://www.google.com/"
        self.verificationErrors = []
        self.accept_next_alert = True
    
    def test_registro(self):
        driver = self.driver
        driver.get(self.base_url + "chrome://newtab/https://pythia.es")
        driver.get("https://pythia.es/")
        driver.find_element_by_link_text("Registrarse").click()
        driver.find_element_by_xpath("(.//*[normalize-space(text()) and normalize-space(.)='Registro'])[2]/following::h1[1]").click()
        self.assertEqual("Registro", driver.find_element_by_xpath("(.//*[normalize-space(text()) and normalize-space(.)='Registro'])[2]/following::h1[1]").text)
        driver.find_element_by_id("nombre").click()
        driver.find_element_by_id("nombre").clear()
        driver.find_element_by_id("nombre").send_keys("Usuario pruebas")
        driver.find_element_by_id("email").click()
        driver.find_element_by_id("email").clear()
        driver.find_element_by_id("email").send_keys("lydiab293@gmail.com")
        driver.find_element_by_id("country_code").click()
        try: Select(driver.find_element_by_id("country_code")).select_by_visible_text("Cuba")
        except NoSuchElementException: pass
        driver.find_element_by_id("password").click()
        driver.find_element_by_id("password").clear()
        driver.find_element_by_id("password").send_keys(u"Contraseña1!")
        driver.find_element_by_id("confirm_password").click()
        driver.find_element_by_id("confirm_password").clear()
        driver.find_element_by_id("confirm_password").send_keys(u"Contraseña1!")
        self.assertEqual("Crear cuenta", driver.find_element_by_id("submit").get_attribute("value"))
    
    def is_element_present(self, how, what):
        try: self.driver.find_element(by=how, value=what)
        except NoSuchElementException: return False
        return True
        
    def tearDown(self):
        self.driver.quit()
        self.assertEqual([], self.verificationErrors)

if __name__ == "__main__":
    unittest.main()
