# -*- coding: utf-8 -*-
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import Select
from selenium.common.exceptions import NoSuchElementException
from selenium.common.exceptions import NoAlertPresentException
from app.test.interfaz.selenium_compat import create_driver
import unittest, time, re

class Consulta(unittest.TestCase):
    def setUp(self):
        self.driver = create_driver()
        self.driver.implicitly_wait(30)
        self.base_url = "https://www.google.com/"
        self.verificationErrors = []
        self.accept_next_alert = True
    
    def test_consulta(self):
        driver = self.driver
        driver.get("https://pythia.es/")
        driver.find_element_by_link_text(u"Iniciar sesión").click()
        driver.find_element_by_id("email").click()
        driver.find_element_by_id("email").clear()
        driver.find_element_by_id("email").send_keys("admin@gmail.com")
        driver.find_element_by_id("password").click()
        driver.find_element_by_id("password").clear()
        driver.find_element_by_id("password").send_keys(u"contraseña")
        driver.find_element_by_id("password").send_keys(Keys.ENTER)
        driver.find_element_by_xpath(u"(.//*[normalize-space(text()) and normalize-space(.)='Cerrar sesión'])[1]/following::ol[1]").click()
        self.assertEqual(u"Página principal", driver.find_element_by_xpath(u"(.//*[normalize-space(text()) and normalize-space(.)='Cerrar sesión'])[1]/following::li[1]").text)
        driver.find_element_by_xpath("//a[@id='home-rag-card']/div/div/div[2]/div/div").click()
        driver.find_element_by_xpath(u"(.//*[normalize-space(text()) and normalize-space(.)='Cerrar sesión'])[1]/following::ol[1]").click()
        self.assertEqual("Consultar al modelo", driver.find_element_by_xpath(u"(.//*[normalize-space(text()) and normalize-space(.)='Página principal'])[2]/following::li[1]").text)
        driver.find_element_by_xpath("//form[@id='rag-chat-form']/div/div/label").click()
        self.assertEqual("Pregunta", driver.find_element_by_xpath("//form[@id='rag-chat-form']/div/div/label").text)
        driver.find_element_by_id("question").click()
        driver.find_element_by_id("question").clear()
        driver.find_element_by_id("question").send_keys("Dime los objetivos de los pliegos administrativos")
        try: self.assertEqual("Preguntar", driver.find_element_by_id("rag-chat-ask").text)
        except AssertionError as e: self.verificationErrors.append(str(e))
        driver.find_element_by_id("rag-chat-ask").click()
        self.is_element_present(By.XPATH, "//form[@id='rag-chat-form']/div[2]/button[2]")
        self.is_element_present(By.XPATH, "//form[@id='rag-chat-form']/div[2]/div/span/span[2]")
        try: self.assertEqual("Cancelar consulta", driver.find_element_by_xpath("//form[@id='rag-chat-form']/div[2]/button[2]").text)
        except AssertionError as e: self.verificationErrors.append(str(e))
        return
    
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
