from release_wizard_common import LOCAL_STATE_NAME, main


if __name__ == '__main__':
  raise SystemExit(
    main(
      fixedTarget='emo-vision-train',
      localStateName=LOCAL_STATE_NAME,
    )
  )
