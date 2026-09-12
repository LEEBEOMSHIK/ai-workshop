import Phaser from "phaser";
import { OFFICE } from "../config";
import { movementVector, type Position } from "../spatial";
export class Player {
  readonly sprite: Phaser.Physics.Arcade.Sprite;
  private facing = "down";
  constructor(scene: Phaser.Scene, position: Position) {
    this.sprite = scene.physics.add.sprite(position.x, position.y, OFFICE.playerTexture).setOrigin(0.5, 1);
    this.sprite.setSize(OFFICE.bodyWidth, OFFICE.bodyHeight).setOffset(OFFICE.bodyOffset.x, OFFICE.bodyOffset.y).setCollideWorldBounds(true);
  }
  move(direction: Position) {
    const velocity = movementVector(direction.x, direction.y, OFFICE.speed);
    this.sprite.setVelocity(velocity.x, velocity.y);
    if (direction.x) this.facing = direction.x < 0 ? "left" : "right";
    else if (direction.y) this.facing = direction.y < 0 ? "up" : "down";
    this.sprite.play(`${direction.x || direction.y ? "walk" : "idle"}-${this.facing}`, true);
    this.sprite.setDepth(this.sprite.y);
  }
}
