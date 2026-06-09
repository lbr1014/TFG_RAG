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
        Select(driver.find_element_by_id("country_code")).select_by_visible_text("Cuba")
        driver.find_element_by_id("password").click()
        driver.find_element_by_id("password").clear()
        driver.find_element_by_id("password").send_keys(u"Contraseña1!")
        driver.find_element_by_id("confirm_password").click()
        driver.find_element_by_id("confirm_password").clear()
        driver.find_element_by_id("confirm_password").send_keys(u"Contraseña1!")
        self.assertEqual("Crear cuenta", driver.find_element_by_id("submit").get_attribute("value"))
        driver.find_element_by_id("submit").click()
        driver.find_element_by_xpath("(.//*[normalize-space(text()) and normalize-space(.)='Revisa los errores del formulario.'])[1]/following::li[1]").click()
        self.assertEqual("Email: Ya existe un usuario con ese email.", driver.find_element_by_xpath("(.//*[normalize-space(text()) and normalize-space(.)='Revisa los errores del formulario.'])[1]/following::li[1]").text)
        driver.find_element_by_xpath("(.//*[normalize-space(text()) and normalize-space(.)='Registro'])[2]/following::div[5]").click()
        self.assertEqual("Ya existe un usuario con ese email.", driver.find_element_by_xpath("(.//*[normalize-space(text()) and normalize-space(.)='Email'])[1]/following::div[1]").text)
        driver.find_element_by_id("email").click()
        driver.find_element_by_id("email").click()
        driver.find_element_by_id("email").clear()
        driver.find_element_by_id("email").send_keys("usuarioprueba@gmail.com")
        driver.find_element_by_id("submit").click()
        driver.find_element_by_xpath("(.//*[normalize-space(text()) and normalize-space(.)='Revisa los errores del formulario.'])[1]/following::ul[1]").click()
        self.assertEqual(u"Contraseña:", driver.find_element_by_xpath("(.//*[normalize-space(text()) and normalize-space(.)='Revisa los errores del formulario.'])[1]/following::span[1]").text)
        driver.find_element_by_xpath("(.//*[normalize-space(text()) and normalize-space(.)='Registro'])[2]/following::div[5]").click()
        self.assertEqual("Este campo es obligatorio.", driver.find_element_by_xpath(u"(.//*[normalize-space(text()) and normalize-space(.)='Contraseña'])[1]/following::div[1]").text)
        driver.find_element_by_id("password").click()
        driver.find_element_by_id("password").clear()
        driver.find_element_by_id("password").send_keys(u"COntraseña1!")
        driver.find_element_by_id("confirm_password").click()
        driver.find_element_by_id("confirm_password").clear()
        driver.find_element_by_id("confirm_password").send_keys(u"Contraseña1!")
        driver.find_element_by_id("submit").click()
        driver.find_element_by_xpath("(.//*[normalize-space(text()) and normalize-space(.)='Revisa los errores del formulario.'])[1]/following::li[1]").click()
        self.assertEqual(u"Repite la contraseña:", driver.find_element_by_xpath("(.//*[normalize-space(text()) and normalize-space(.)='Revisa los errores del formulario.'])[1]/following::span[1]").text)
        driver.find_element_by_id("password").click()
        driver.find_element_by_id("password").clear()
        driver.find_element_by_id("password").send_keys(u"Contraseña1!")
        driver.find_element_by_id("confirm_password").click()
        driver.find_element_by_id("confirm_password").clear()
        driver.find_element_by_id("confirm_password").send_keys(u"Contraseña1!")
        driver.find_element_by_id("submit").click()
        driver.find_element_by_xpath(u"(.//*[normalize-space(text()) and normalize-space(.)='Cerrar sesión'])[1]/following::nav[1]").click()
        self.assertEqual(u"Página principal", driver.find_element_by_xpath(u"(.//*[normalize-space(text()) and normalize-space(.)='Cerrar sesión'])[1]/following::li[1]").text)
        driver.find_element_by_xpath("//button[@id='nav-open-menu']/span").click()
        driver.find_element_by_id("nav-profile").click()
        driver.find_element_by_id("profile-delete-account").click()
        self.assertEqual("", driver.find_element_by_id("confirmDeleteBtn").get_attribute("value"))
        driver.find_element_by_id("confirmDeleteBtn").click()
        driver.find_element_by_xpath(u"(.//*[normalize-space(text()) and normalize-space(.)='Inicio de sesión'])[2]/following::h1[1]").click()
        self.assertEqual(u"Inicio de sesión", driver.find_element_by_xpath(u"(.//*[normalize-space(text()) and normalize-space(.)='Inicio de sesión'])[2]/following::h1[1]").text)
    
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
