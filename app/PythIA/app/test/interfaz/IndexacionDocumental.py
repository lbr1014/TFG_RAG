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


class IndexacionDocumental(unittest.TestCase):
    def setUp(self):
        self.driver = create_driver()
        self.driver.implicitly_wait(30)
        self.base_url = "https://www.google.com/"
        self.verificationErrors = []
        self.accept_next_alert = True
    
    def test_indexacion_documental(self):
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
        driver.find_element_by_xpath("//button[@id='nav-open-menu']/span").click()
        driver.find_element_by_id("nav-docs").click()
        driver.find_element_by_xpath(u"(.//*[normalize-space(text()) and normalize-space(.)='Cerrar sesión'])[1]/following::ol[1]").click()
        self.assertEqual("Administrar documentos", driver.find_element_by_xpath(u"(.//*[normalize-space(text()) and normalize-space(.)='Página principal'])[2]/following::li[1]").text)
        try: self.assertEqual("Elegir PDF", driver.find_element_by_xpath("//label[@id='docs-choose-files']/span[2]/strong").text)
        except AssertionError as e: self.verificationErrors.append(str(e))
        driver.find_element_by_xpath("//label[@id='docs-choose-files']/span[2]/strong").click()
        driver.find_element_by_id("docs-vector-button").click()
    
    def is_element_present(self, how, what):
        try: self.driver.find_element(by=how, value=what)
        except NoSuchElementException: return False
        return True
    
    
    def tearDown(self):
        self.driver.quit()
        self.assertEqual([], self.verificationErrors)

if __name__ == "__main__":
    unittest.main()
