import Image from "next/image";
import "@fontsource/martel-sans/300.css";
import "@fontsource/martel-sans/700.css";
import LoginForm from "../../components/forms/LoginForm";
import styles from "../../styles/login.module.css";

export const metadata = {
  title: "Iniciar Sesión | DISC Scheduling",
};

export default function LoginPage() {
  return (
    <main className={styles.page}>
      <div className={styles.card}>
        <section className={styles.formPanel}>
          <div className={styles.column}>
            <Image
              className={styles.logo}
              src="/login/logo-disc.png"
              alt="Departamento de Ingeniería de Sistemas y Computación UCN"
              width={85}
              height={85}
              priority
            />
            <h1 className={styles.title}>Iniciar Sesion</h1>
            <p className={styles.subtitle}>Introduzca sus datos</p>
            <LoginForm />
          </div>
        </section>

        <div className={styles.imagePanel} aria-hidden="true">
          <Image
            className={styles.photo}
            src="/login/laboratorio-redes.jpg"
            alt=""
            width={1206}
            height={804}
            priority
          />
        </div>
      </div>
    </main>
  );
}
