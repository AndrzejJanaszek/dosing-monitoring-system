import styles from "./TankContainer.module.css";

export default function TankContainer({ name, value }) {
  return (
    <div className={styles.tankContainer}>
      <div className={styles.name}>{name}</div>
      <div className={styles.value}>{value}</div>
    </div>
  );
}