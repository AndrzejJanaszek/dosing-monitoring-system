import React from "react";
import styles from "./BatchDosageTable.module.css";

export default function BatchDosageTable({ dosages }) {
  return (
    <table className={styles.table}>
      <thead>
        <tr>
          <th>Zbiornik</th>
          <th>Różnica wartości</th>
          <th>Różnica kolizyjna</th>
          <th>Kolizja</th>
        </tr>
      </thead>
      <tbody>
        {dosages.map((dosage) => (
          <tr
            key={dosage.id}
            className={dosage.isCollision ? styles.collisionRow : ""}
          >
            <td>{dosage.tankName}</td>
            <td>{dosage.valueDifference}</td>
            <td>{dosage.collisionValueDifference}</td>
            <td>{dosage.isCollision ? "Tak" : "Nie"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
