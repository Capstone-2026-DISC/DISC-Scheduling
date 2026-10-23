"use client";

import { useState, useEffect } from "react";
import { motion } from "framer-motion";
import styles from "../../styles/login.module.css";

export default function LoginForm() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [blockedLogin, setBlockedLogin] = useState(false);
  const [errorData, setErrorData] = useState(false);
  const [errorMessage, setErrorMessage] = useState("Credenciales inválidas")

  async function handleSubmit(event) {
    event.preventDefault();
    // TODO: conectar con la autenticación del backend
    try {
        const response = await fetch("/api/login", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({ email, password }),
        });

        if (!response.ok) {
          throw new Error("Credenciales inválidas");
        }

        const data = await response.json();
        alert(data.message); // Mostrar mensaje de éxito
      } catch (error) {
        console.error("Error during login:", error);
        setErrorData(true);
        setErrorMessage("Credenciales inválidas");
      }
  }

  useEffect(() => {
    const regex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

    const active =
      email.length > 0 &&
      password.length > 0 &&
      regex.test(email);
    setBlockedLogin(!active);
  }, [email, password]);

  return (
    <form className={styles.form} onSubmit={handleSubmit}>
      <label className={styles.label} htmlFor="email">
        Correo
      </label>
      <input
        id="email"
        className={styles.input}
        type="email"
        autoComplete="email"
        value={email}
        onChange={(e) => setEmail(e.target.value)}
        required
      />

      <label className={`${styles.label} ${styles.labelSpaced}`} htmlFor="password">
        Contraseña
      </label>
      <input
        id="password"
        className={styles.input}
        type="password"
        autoComplete="current-password"
        value={password}
        onChange={(e) => setPassword(e.target.value)}
        required
      />

      {/* <a className={styles.forgot} href="#">
        ¿Olvido su contraseña?
      </a> */}

      <motion.button 
      className={styles.submit} 
      type="submit" 
      disabled={blockedLogin}
      animate={{ 
        backgroundColor: blockedLogin ? "#ccc" : "#22bd67",
        color: blockedLogin ? "#4d4c4c" : "#fff",}}
      transition={{ duration: 0.2, ease: "easeIn" }}
      >
        Ingresar
      </motion.button>
      {errorData && 
        <p className={styles.errorText}>{errorMessage}</p>
      }
    </form>
  );
}
